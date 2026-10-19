"""
Cutia Clasei · platforma internă a cursului de vibe coding.

Spațiul privat (student ↔ trainer): mesaje directe, întrebări, teme & proiecte.
Spațiul public (toată clasa): cutia de idei, AI News, ghidul, clasamentul.
Toate regulile de acces se verifică aici, pe server.
"""

import asyncio
import base64
import contextvars
import copy
import random
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import os
import secrets
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

current_dir = Path(__file__).parent


def load_env_file(path: Path):
    """Citește KEY=VALUE din .env (fișier ignorat de git). Variabilele deja
    setate în mediu au prioritate. Cheia API rămâne doar pe server."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(current_dir.parent / ".env")

try:
    from . import ai, digest, news, points, repocheck, store, tools, webpush
except ImportError:  # rulare directă: python app.py
    import store
    import webpush
    import ai
    import digest
    import repocheck
    import tools
    import news
    import points

# Pe Vercel (sau altă gazdă „serverless”) nu avem fire în fundal și nici disc: datele stau în Supabase,
# briefing-ul îl pornește Vercel Cron, iar o cerere poate avea maxim ~4,5 MB.
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("CUTIA_SERVERLESS") == "1")

DATA_FILE = Path(os.environ.get("CUTIA_DATA", current_dir.parent / "data" / "cutia.json"))
UPLOAD_DIR = Path(os.environ.get("CUTIA_UPLOADS", DATA_FILE.parent / "uploads"))
# Un cod de trainer scris în README sau în .env.example îl știe oricine: îl ignorăm
WEAK_TRAINER_CODES = {"trainer", "schimba-ma", "secret", "parola", "password", "admin", "123456"}
TRAINER_CODE = os.environ.get("TRAINER_CODE", "").strip()
if TRAINER_CODE.lower() in WEAK_TRAINER_CODES and os.environ.get("CUTIA_ALLOW_WEAK_CODE") != "1" or len(TRAINER_CODE) < 6:
    TRAINER_CODE = ""

@asynccontextmanager
async def lifespan(_app):
    if not SERVERLESS:
        start_byte()  # robotul de știri (definit mai jos, la „Byte”); pe Vercel îl pornește Vercel Cron
    yield


app = FastAPI(title="Cutia Clasei API",
              description="Întrebări pentru trainer și propuneri de proiecte", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Limba: interfața trimite antetul X-Lang (ro, en, fr, it, es, de); mesajele
# de eroare și textele AI vin în limba aleasă.
# ---------------------------------------------------------------------------

current_lang = contextvars.ContextVar("current_lang", default="ro")

# Ordinea traducerilor: ro, en, fr, it, es, de (ca în ai.LANGS)
MESSAGES = {
    "short_password": ("Parola trebuie să aibă minim 8 caractere.", "Password must be at least 8 characters.", "Le mot de passe doit avoir au moins 8 caractères.", "La password deve avere almeno 8 caratteri.", "La contraseña debe tener al menos 8 caracteres.", "Das Passwort muss mindestens 8 Zeichen haben."),
    "bad_email": ("Adresa de email nu pare corectă.", "That email address doesn't look right.", "Cette adresse e-mail ne semble pas correcte.", "Questo indirizzo email non sembra corretto.", "Ese correo no parece correcto.", "Diese E-Mail-Adresse sieht nicht richtig aus."),
    "email_taken": ("Există deja un cont cu acest email. Intră în cont.", "An account with this email already exists. Sign in instead.", "Un compte existe déjà avec cet e-mail. Connecte-toi.", "Esiste già un account con questa email. Accedi.", "Ya existe una cuenta con este correo. Inicia sesión.", "Mit dieser E-Mail gibt es schon ein Konto. Melde dich an."),
    "wrong_login": ("Utilizator sau parolă greșită.", "Wrong username or password.", "Identifiant ou mot de passe incorrect.", "Utente o password errati.", "Usuario o contraseña incorrectos.", "Benutzername oder Passwort falsch."),
    "bad_username": ("Utilizatorul are 3–32 caractere: litere mici, cifre, punct, minus sau _ (fără spații).", "Usernames are 3–32 characters: lowercase letters, digits, dot, dash or _ (no spaces).", "L'identifiant fait 3 à 32 caractères : minuscules, chiffres, point, tiret ou _ (sans espaces).", "Il nome utente ha 3–32 caratteri: lettere minuscole, cifre, punto, trattino o _ (senza spazi).", "El usuario tiene 3–32 caracteres: minúsculas, números, punto, guion o _ (sin espacios).", "Der Benutzername hat 3–32 Zeichen: Kleinbuchstaben, Ziffern, Punkt, Bindestrich oder _ (ohne Leerzeichen)."),
    "username_taken": ("Există deja un student cu acest utilizator. Alege altul.", "A student with this username already exists. Pick another one.", "Un étudiant avec cet identifiant existe déjà. Choisis-en un autre.", "Esiste già uno studente con questo nome utente. Scegline un altro.", "Ya existe un estudiante con este usuario. Elige otro.", "Diesen Benutzernamen gibt es schon. Wähl einen anderen."),
    "setup_off": ("Contul de trainer se face cu TRAINER_CODE, care nu e setat pe server.", "The trainer account needs TRAINER_CODE, which isn't set on the server.", "Le compte formateur nécessite TRAINER_CODE, qui n'est pas défini sur le serveur.", "L'account trainer richiede TRAINER_CODE, che non è impostato sul server.", "La cuenta de formador necesita TRAINER_CODE, que no está configurado en el servidor.", "Das Trainer-Konto braucht TRAINER_CODE, das auf dem Server nicht gesetzt ist."),
    "not_trainer_email": ("Acest email nu e în lista de traineri (TRAINER_EMAILS).", "This email isn't on the trainer list (TRAINER_EMAILS).", "Cet e-mail n'est pas dans la liste des formateurs (TRAINER_EMAILS).", "Questa email non è nell'elenco dei trainer (TRAINER_EMAILS).", "Este correo no está en la lista de formadores (TRAINER_EMAILS).", "Diese E-Mail steht nicht auf der Trainer-Liste (TRAINER_EMAILS)."),
    "no_storage": ("Serverul nu are unde salva datele: setează SUPABASE_URL și SUPABASE_SECRET_KEY în Vercel.", "The server has nowhere to save data: set SUPABASE_URL and SUPABASE_SECRET_KEY in Vercel.", "Le serveur ne peut pas enregistrer les données : définis SUPABASE_URL et SUPABASE_SECRET_KEY dans Vercel.", "Il server non ha dove salvare i dati: imposta SUPABASE_URL e SUPABASE_SECRET_KEY in Vercel.", "El servidor no tiene dónde guardar los datos: configura SUPABASE_URL y SUPABASE_SECRET_KEY en Vercel.", "Der Server kann keine Daten speichern: setz SUPABASE_URL und SUPABASE_SECRET_KEY in Vercel."),
    "storage_down": ("Baza de date (Supabase) nu răspunde. Încearcă peste un minut.", "The database (Supabase) isn't responding. Try again in a minute.", "La base de données (Supabase) ne répond pas. Réessaie dans une minute.", "Il database (Supabase) non risponde. Riprova tra un minuto.", "La base de datos (Supabase) no responde. Inténtalo en un minuto.", "Die Datenbank (Supabase) antwortet nicht. Versuch es in einer Minute."),
    "storage_busy": ("Mulți colegi scriu chiar acum. Mai încearcă o dată.", "Lots of classmates are writing right now. Try once more.", "Beaucoup de camarades écrivent en ce moment. Réessaie.", "Molti compagni stanno scrivendo ora. Riprova.", "Muchos compañeros están escribiendo ahora. Inténtalo otra vez.", "Gerade schreiben viele gleichzeitig. Versuch es nochmal."),
    "too_many_attempts": ("Prea multe încercări. Mai încearcă peste 10 minute.", "Too many attempts. Try again in 10 minutes.", "Trop de tentatives. Réessaie dans 10 minutes.", "Troppi tentativi. Riprova tra 10 minuti.", "Demasiados intentos. Vuelve a intentarlo en 10 minutos.", "Zu viele Versuche. Versuch es in 10 Minuten wieder."),
    "wrong_current": ("Parola actuală nu e corectă.", "Your current password isn't right.", "Le mot de passe actuel n'est pas correct.", "La password attuale non è corretta.", "La contraseña actual no es correcta.", "Das aktuelle Passwort stimmt nicht."),
    "login_again": ("Autentifică-te din nou.", "Please sign in again.", "Reconnecte-toi.", "Accedi di nuovo.", "Vuelve a iniciar sesión.", "Bitte melde dich erneut an."),
    "trainer_only": ("Doar trainerul poate face asta.", "Only the trainer can do this.", "Seul le formateur peut faire ça.", "Solo il trainer può farlo.", "Solo el formador puede hacer esto.", "Nur der Trainer kann das tun."),
    "student_only": ("Doar studenții pot face asta.", "Only students can do this.", "Seuls les étudiants peuvent faire ça.", "Solo gli studenti possono farlo.", "Solo los estudiantes pueden hacer esto.", "Nur Studierende können das tun."),
    "need_trainer_code": ("Acesta e emailul trainerului: scrie și codul de trainer.", "This is the trainer's email: enter the trainer code too.", "C'est l'e-mail du formateur : saisis aussi le code formateur.", "Questa è l'email del trainer: inserisci anche il codice trainer.", "Este es el correo del formador: escribe también el código de formador.", "Das ist die Trainer-E-Mail: gib auch den Trainer-Code ein."),
    "registration_closed": ("Înscrierile sunt închise. Cere-i trainerului un cont.", "Sign-ups are closed. Ask the trainer for an account.", "Les inscriptions sont fermées. Demande un compte au formateur.", "Le iscrizioni sono chiuse. Chiedi un account al trainer.", "Las inscripciones están cerradas. Pide una cuenta al formador.", "Die Anmeldung ist geschlossen. Bitte den Trainer um ein Konto."),
    "need_name": ("Scrie-ți numele.", "Enter your name.", "Écris ton nom.", "Scrivi il tuo nome.", "Escribe tu nombre.", "Gib deinen Namen ein."),
    "wrong_code": ("Cod de trainer greșit.", "Wrong trainer code.", "Code formateur incorrect.", "Codice trainer errato.", "Código de formador incorrecto.", "Falscher Trainer-Code."),
    "too_short": ("Textul e prea scurt.", "The text is too short.", "Le texte est trop court.", "Il testo è troppo corto.", "El texto es demasiado corto.", "Der Text ist zu kurz."),
    "no_question": ("Întrebarea nu există.", "Question not found.", "Question introuvable.", "Domanda non trovata.", "Pregunta no encontrada.", "Frage nicht gefunden."),
    "not_yours": ("Poți cere răspuns AI doar pentru întrebările tale.", "You can only ask the AI about your own questions.", "Tu ne peux demander l'IA que pour tes propres questions.", "Puoi chiedere all'IA solo sulle tue domande.", "Solo puedes pedir a la IA sobre tus propias preguntas.", "Du kannst die KI nur zu deinen eigenen Fragen fragen."),
    "ai_off": ("AI-ul nu e configurat pe server (lipsește cheia API).", "AI is not configured on the server (missing API key).", "L'IA n'est pas configurée sur le serveur (clé API manquante).", "L'IA non è configurata sul server (manca la chiave API).", "La IA no está configurada en el servidor (falta la clave API).", "Die KI ist auf dem Server nicht eingerichtet (API-Schlüssel fehlt)."),
    "ai_failed": ("AI-ul nu a putut răspunde acum. Încearcă din nou.", "The AI couldn't answer right now. Try again.", "L'IA n'a pas pu répondre. Réessaie.", "L'IA non ha potuto rispondere. Riprova.", "La IA no pudo responder. Inténtalo de nuevo.", "Die KI konnte gerade nicht antworten. Versuch es nochmal."),
    "empty_idea": ("Scrie măcar o idee înainte de retușare.", "Write at least an idea before the AI touch-up.", "Écris au moins une idée avant la retouche IA.", "Scrivi almeno un'idea prima del ritocco IA.", "Escribe al menos una idea antes del retoque IA.", "Schreib zuerst eine Idee, bevor die KI sie überarbeitet."),
    "approve_first": ("Aprobă varianta finală înainte să o trimiți.", "Approve the final version before submitting it.", "Approuve la version finale avant de l'envoyer.", "Approva la versione finale prima di inviarla.", "Aprueba la versión final antes de enviarla.", "Bestätige die finale Version, bevor du sie sendest."),
    "missing": ("Lipsește: {}.", "Missing: {}.", "Il manque : {}.", "Manca: {}.", "Falta: {}.", "Es fehlt: {}."),
    "no_proposal": ("Propunerea nu există.", "Proposal not found.", "Proposition introuvable.", "Proposta non trovata.", "Propuesta no encontrada.", "Vorschlag nicht gefunden."),
    "withdrawn": ("Propunerea a fost retrasă de autor.", "The author withdrew this proposal.", "L'auteur a retiré cette proposition.", "L'autore ha ritirato questa proposta.", "El autor retiró esta propuesta.", "Der Vorschlag wurde vom Autor zurückgezogen."),
    "not_author": ("Doar autorul poate face asta.", "Only the author can do this.", "Seul l'auteur peut faire ça.", "Solo l'autore può farlo.", "Solo el autor puede hacer esto.", "Nur der Autor kann das tun."),
    "too_many_drafts": ("Poți păstra maxim {} ciorne. Șterge una veche.", "You can keep at most {} drafts. Delete an old one.", "Tu peux garder au maximum {} brouillons. Supprimes-en un ancien.", "Puoi tenere al massimo {} bozze. Eliminane una vecchia.", "Puedes guardar como máximo {} borradores. Borra uno antiguo.", "Du kannst höchstens {} Entwürfe behalten. Lösch einen alten."),
    "no_draft": ("Ciorna nu există.", "Draft not found.", "Brouillon introuvable.", "Bozza non trovata.", "Borrador no encontrado.", "Entwurf nicht gefunden."),
    "own_vote": ("Nu-ți poți vota propria idee.", "You can't vote for your own idea.", "Tu ne peux pas voter pour ta propre idée.", "Non puoi votare la tua idea.", "No puedes votar tu propia idea.", "Du kannst nicht für deine eigene Idee stimmen."),
    "no_submission": ("Predarea nu există.", "Submission not found.", "Rendu introuvable.", "Consegna non trovata.", "Entrega no encontrada.", "Abgabe nicht gefunden."),
    "need_title": ("Scrie un titlu.", "Add a title.", "Ajoute un titre.", "Aggiungi un titolo.", "Añade un título.", "Füge einen Titel hinzu."),
    "bad_link": ("Linkul trebuie să înceapă cu https:// sau http://.", "The link must start with https:// or http://.", "Le lien doit commencer par https:// ou http://.", "Il link deve iniziare con https:// o http://.", "El enlace debe empezar por https:// o http://.", "Der Link muss mit https:// oder http:// beginnen."),
    "too_many_files": ("Poți încărca maxim {} fișiere.", "You can upload at most {} files.", "Tu peux envoyer au maximum {} fichiers.", "Puoi caricare al massimo {} file.", "Puedes subir como máximo {} archivos.", "Du kannst höchstens {} Dateien hochladen."),
    "file_too_big": ("Fișierul {} e prea mare (maxim {} MB).", "File {} is too big (max {} MB).", "Le fichier {} est trop gros (max {} Mo).", "Il file {} è troppo grande (max {} MB).", "El archivo {} es demasiado grande (máx. {} MB).", "Die Datei {} ist zu groß (max. {} MB)."),
    "bad_file_type": ("Tipul fișierului {} nu e acceptat.", "File type of {} is not allowed.", "Le type du fichier {} n'est pas accepté.", "Il tipo del file {} non è consentito.", "El tipo del archivo {} no está permitido.", "Der Dateityp von {} ist nicht erlaubt."),
    "empty_submission": ("Adaugă un fișier, un link sau un mesaj.", "Add a file, a link or a message.", "Ajoute un fichier, un lien ou un message.", "Aggiungi un file, un link o un messaggio.", "Añade un archivo, un enlace o un mensaje.", "Füge eine Datei, einen Link oder eine Nachricht hinzu."),
    "no_student": ("Studentul nu există.", "Student not found.", "Étudiant introuvable.", "Studente non trovato.", "Estudiante no encontrado.", "Student nicht gefunden."),
    "no_assignment": ("Tema nu există.", "Assignment not found.", "Devoir introuvable.", "Compito non trovato.", "Tarea no encontrada.", "Aufgabe nicht gefunden."),
    "bad_points": ("Punctele trebuie să fie între -100 și 100, diferite de 0.", "Points must be between -100 and 100, not 0.", "Les points doivent être entre -100 et 100, sauf 0.", "I punti devono essere tra -100 e 100, diversi da 0.", "Los puntos deben estar entre -100 y 100, distintos de 0.", "Punkte müssen zwischen -100 und 100 liegen, nicht 0."),
    "need_reason": ("Scrie motivul bonusului.", "Add a reason for the bonus.", "Indique la raison du bonus.", "Scrivi il motivo del bonus.", "Escribe el motivo del bonus.", "Gib einen Grund für den Bonus an."),
    "not_github": ("Pune linkul repo-ului de GitHub, de forma https://github.com/nume/repo.", "Paste your GitHub repo link, like https://github.com/name/repo.", "Colle le lien de ton dépôt GitHub, comme https://github.com/nom/depot.", "Incolla il link del repo GitHub, tipo https://github.com/nome/repo.", "Pega el enlace de tu repo de GitHub, como https://github.com/nombre/repo.", "Füge den Link zu deinem GitHub-Repo ein, z. B. https://github.com/name/repo."),
    "repo_not_found": ("Nu găsesc repo-ul. Verifică linkul sau fă-l public (Settings → General → Danger Zone → Change visibility).", "Can't find that repo. Check the link or make it public (Settings → General → Danger Zone → Change visibility).", "Dépôt introuvable. Vérifie le lien ou rends-le public (Settings → General → Danger Zone → Change visibility).", "Repo non trovato. Controlla il link o rendilo pubblico (Settings → General → Danger Zone → Change visibility).", "No encuentro el repo. Revisa el enlace o hazlo público (Settings → General → Danger Zone → Change visibility).", "Repo nicht gefunden. Prüf den Link oder mach es öffentlich (Settings → General → Danger Zone → Change visibility)."),
    "github_busy": ("GitHub ne-a limitat cererile. Mai încearcă peste câteva minute.", "GitHub is limiting our requests. Try again in a few minutes.", "GitHub limite nos requêtes. Réessaie dans quelques minutes.", "GitHub sta limitando le richieste. Riprova tra qualche minuto.", "GitHub está limitando las peticiones. Inténtalo en unos minutos.", "GitHub begrenzt gerade die Anfragen. Versuch es in ein paar Minuten."),
    "github_down": ("Nu am putut citi repo-ul de pe GitHub acum. Încearcă din nou.", "Couldn't read the repo from GitHub right now. Try again.", "Impossible de lire le dépôt sur GitHub. Réessaie.", "Impossibile leggere il repo da GitHub ora. Riprova.", "No se pudo leer el repo de GitHub. Inténtalo de nuevo.", "Das Repo konnte gerade nicht von GitHub gelesen werden. Versuch es nochmal."),
    "slow_down": ("Încă puțin: poți încerca din nou peste {} secunde.", "Hang on: you can try again in {} seconds.", "Un instant : tu pourras réessayer dans {} secondes.", "Un attimo: puoi riprovare tra {} secondi.", "Un momento: puedes intentarlo en {} segundos.", "Moment: du kannst es in {} Sekunden wieder versuchen."),
    "need_error": ("Lipește mesajul de eroare sau adaugă o captură de ecran.", "Paste the error message or add a screenshot.", "Colle le message d'erreur ou ajoute une capture d'écran.", "Incolla il messaggio di errore o aggiungi uno screenshot.", "Pega el mensaje de error o añade una captura.", "Füge die Fehlermeldung oder einen Screenshot ein."),
    "bad_image": ("Captura trebuie să fie PNG, JPG sau WebP, de maxim {} MB.", "The screenshot must be PNG, JPG or WebP, max {} MB.", "La capture doit être en PNG, JPG ou WebP, {} Mo max.", "Lo screenshot deve essere PNG, JPG o WebP, max {} MB.", "La captura debe ser PNG, JPG o WebP, de {} MB como máximo.", "Der Screenshot muss PNG, JPG oder WebP sein, max. {} MB."),
    "no_item": ("Nu există.", "Not found.", "Introuvable.", "Non trovato.", "No encontrado.", "Nicht gefunden."),
    "own_like": ("Nu-ți poți aprecia propriul prompt.", "You can't like your own prompt.", "Tu ne peux pas aimer ton propre prompt.", "Non puoi mettere like al tuo prompt.", "No puedes dar me gusta a tu propio prompt.", "Du kannst deinen eigenen Prompt nicht liken."),
    "too_many_posts": ("Ai atins limita de {}. Șterge unul mai vechi.", "You've reached the limit of {}. Delete an older one.", "Tu as atteint la limite de {}. Supprimes-en un ancien.", "Hai raggiunto il limite di {}. Eliminane uno vecchio.", "Has llegado al límite de {}. Borra uno anterior.", "Du hast das Limit von {} erreicht. Lösch einen älteren."),
    "live_off": ("Nu e nicio oră live acum.", "There's no live class right now.", "Aucun cours en direct pour l'instant.", "Nessuna lezione live in questo momento.", "No hay ninguna clase en vivo ahora.", "Gerade läuft keine Live-Stunde."),
    "poll_closed": ("Votul s-a închis.", "Voting is closed.", "Le vote est clos.", "La votazione è chiusa.", "La votación está cerrada.", "Die Abstimmung ist geschlossen."),
    "poll_options": ("Scrie între 2 și 4 variante.", "Write between 2 and 4 options.", "Écris entre 2 et 4 options.", "Scrivi da 2 a 4 opzioni.", "Escribe entre 2 y 4 opciones.", "Schreib 2 bis 4 Optionen."),
    "no_ticket": ("Trainerul n-a pus încă întrebarea de final.", "The trainer hasn't posted the exit question yet.", "Le formateur n'a pas encore posé la question de fin.", "Il trainer non ha ancora posto la domanda finale.", "El formador aún no ha puesto la pregunta final.", "Der Trainer hat die Abschlussfrage noch nicht gestellt."),
    "own_react": ("Nu poți reacționa la propriul proiect.", "You can't react to your own project.", "Tu ne peux pas réagir à ton propre projet.", "Non puoi reagire al tuo progetto.", "No puedes reaccionar a tu propio proyecto.", "Du kannst nicht auf dein eigenes Projekt reagieren."),
    "need_link": ("Adaugă linkul live sau linkul repo-ului.", "Add the live link or the repo link.", "Ajoute le lien en ligne ou le lien du dépôt.", "Aggiungi il link live o quello del repo.", "Añade el enlace en vivo o el del repo.", "Füge den Live-Link oder den Repo-Link hinzu."),
    "not_chosen": ("Kitul de start apare după ce trainerul alege ideea.", "The kickstart kit appears once the trainer chooses the idea.", "Le kit de démarrage apparaît quand le formateur choisit l'idée.", "Il kit di avvio appare quando il trainer sceglie l'idea.", "El kit de inicio aparece cuando el formador elige la idea.", "Das Starter-Kit erscheint, sobald der Trainer die Idee auswählt."),
    "bad_date": ("Data nu e corectă.", "That date isn't right.", "La date n'est pas correcte.", "La data non è corretta.", "La fecha no es correcta.", "Das Datum stimmt nicht."),
    "bad_subscription": ("Abonamentul pentru notificări nu e valid.", "The notification subscription isn't valid.", "L'abonnement aux notifications n'est pas valide.", "L'iscrizione alle notifiche non è valida.", "La suscripción a notificaciones no es válida.", "Das Benachrichtigungs-Abo ist ungültig."),
    "push_answer": ("Trainerul ți-a răspuns la o întrebare.", "The trainer answered one of your questions.", "Le formateur a répondu à une de tes questions.", "Il trainer ha risposto a una tua domanda.", "El formador respondió a una de tus preguntas.", "Der Trainer hat eine deiner Fragen beantwortet."),
    "push_dm": ("Ai un mesaj nou.", "You have a new message.", "Tu as un nouveau message.", "Hai un nuovo messaggio.", "Tienes un mensaje nuevo.", "Du hast eine neue Nachricht."),
    "push_feedback": ("Ai feedback nou la o temă.", "You have new feedback on your homework.", "Tu as un nouveau retour sur un devoir.", "Hai un nuovo feedback su un compito.", "Tienes comentarios nuevos sobre una tarea.", "Du hast neues Feedback zu einer Hausaufgabe."),
    "push_decision": ("Trainerul a actualizat statusul propunerii tale.", "The trainer updated the status of your proposal.", "Le formateur a mis à jour le statut de ta proposition.", "Il trainer ha aggiornato lo stato della tua proposta.", "El formador actualizó el estado de tu propuesta.", "Der Trainer hat den Status deines Vorschlags aktualisiert."),
    "refine_limit": ("Ai folosit toate cele {} retușări AI de azi. Poți trimite propunerea și fără retuș.", "You've used all {} AI polishes for today. You can still submit the proposal without one.", "Tu as utilisé les {} retouches IA d'aujourd'hui. Tu peux envoyer la proposition sans retouche.", "Hai usato tutti i {} ritocchi AI di oggi. Puoi inviare la proposta anche senza ritocco.", "Has usado los {} retoques de IA de hoy. Puedes enviar la propuesta sin retoque.", "Du hast alle {} KI-Überarbeitungen für heute verbraucht. Du kannst den Vorschlag auch ohne senden."),
    "no_faq_consent": ("Studentul nu a fost de acord ca întrebarea să apară în FAQ.", "The student hasn't agreed to this question appearing in the FAQ.", "L'étudiant n'a pas accepté que cette question apparaisse dans la FAQ.", "Lo studente non ha acconsentito a pubblicare questa domanda nelle FAQ.", "El estudiante no aceptó que esta pregunta aparezca en las FAQ.", "Der Student hat nicht zugestimmt, dass diese Frage in den FAQ erscheint."),
    "need_answer_first": ("Răspunde mai întâi la întrebare.", "Answer the question first.", "Réponds d'abord à la question.", "Rispondi prima alla domanda.", "Responde primero a la pregunta.", "Beantworte zuerst die Frage."),
    "push_chosen": ("Ideea ta a fost aleasă! 🏆", "Your idea was chosen! 🏆", "Ton idée a été choisie ! 🏆", "La tua idea è stata scelta! 🏆", "¡Tu idea fue elegida! 🏆", "Deine Idee wurde gewählt! 🏆"),
    "push_assignment": ("Temă nouă de la trainer.", "New homework from the trainer.", "Nouveau devoir du formateur.", "Nuovo compito dal trainer.", "Nueva tarea del formador.", "Neue Hausaufgabe vom Trainer."),
    "push_live": ("🔴 Ora live a început. Intră!", "🔴 The live class has started. Join in!", "🔴 Le cours en direct a commencé. Rejoins-nous !", "🔴 La lezione live è iniziata. Entra!", "🔴 La clase en vivo ha empezado. ¡Entra!", "🔴 Die Live-Stunde hat begonnen. Komm rein!"),
    "push_digest": ("📰 Briefing-ul zilei de la Byte e gata.", "📰 Byte's daily briefing is ready.", "📰 Le briefing du jour de Byte est prêt.", "📰 Il briefing del giorno di Byte è pronto.", "📰 El briefing del día de Byte está listo.", "📰 Bytes Tagesbriefing ist fertig."),
    "no_announcement": ("Anunțul nu există.", "Announcement not found.", "Annonce introuvable.", "Annuncio non trovato.", "Anuncio no encontrado.", "Ankündigung nicht gefunden."),
}
FIELD_NAMES = {
    "title": ("titlu", "title", "titre", "titolo", "título", "Titel"),
    "description": ("ce face aplicația", "what the app does", "ce que fait l'app", "cosa fa l'app", "qué hace la app", "was die App macht"),
    "audience": ("cine o folosește", "who uses it", "qui l'utilise", "chi la usa", "quién la usa", "wer sie nutzt"),
}


def lang_index() -> int:
    return ai.LANGS.index(current_lang.get())


def msg(key: str, *args) -> str:
    text = MESSAGES[key][lang_index()]
    return text.format(*args)


def fail(status: int, key: str, *args):
    raise HTTPException(status_code=status, detail=msg(key, *args))


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    lang = request.headers.get("x-lang", "ro")
    current_lang.set(lang if lang in ai.LANGS else "ro")
    return await call_next(request)


import mimetypes
mimetypes.add_type("application/manifest+json", ".webmanifest")
app.mount("/static", StaticFiles(directory=current_dir / "static"), name="static")

# ---------------------------------------------------------------------------
# Stocare: în memorie. Local se salvează într-un fișier JSON; cu Supabase (obligatoriu
# pe Vercel) fiecare cerere citește ce s-a schimbat și scrie ce a schimbat ea.
# ---------------------------------------------------------------------------

_lock = threading.RLock()
DEFAULTS = {
    "users": {}, "revoked": {}, "prefs": {}, "drafts": [],
    "questions": [], "proposals": [], "submissions": [],
    "messages": [], "assignments": [], "announcements": [], "bonuses": [],
    "digests": [], "refine_log": {}, "next_id": 1,
}
db = copy.deepcopy(DEFAULTS)
SESSION_DAYS = 60

# Ce știm că e în Supabase: versiunea și amprenta fiecărei colecții (vezi src/store.py)
_remote = {"versions": {}, "hashes": {}}


def use_supabase() -> bool:
    return os.environ.get("CUTIA_PERSIST", "1") != "0" and store.enabled()


def load_local() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _dump(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def sync_in():
    """Aduce din Supabase doar colecțiile schimbate de altă copie a serverului."""
    rows = store.sync(_remote["versions"])
    with _lock:
        for row in rows:
            if row["changed"]:
                db[row["name"]] = row["data"]
                _remote["hashes"][row["name"]] = _fingerprint(_dump(row["data"]))
            _remote["versions"][row["name"]] = row["version"]


def pending_changes() -> dict:
    """Colecțiile schimbate în memorie față de ce e în Supabase: {nume: (date, amprentă)}."""
    with _lock:
        dumps = {k: _dump(v) for k, v in db.items()}
    out = {}
    for k, text in dumps.items():
        h = _fingerprint(text)
        if _remote["hashes"].get(k) != h:
            out[k] = (json.loads(text), h)
    return out


def discard(names):
    """Uită schimbările locale nescrise: la următoarea sincronizare luăm varianta din Supabase."""
    with _lock:
        for k in names:
            _remote["versions"].pop(k, None)
            _remote["hashes"].pop(k, None)
            if k in DEFAULTS:
                db[k] = copy.deepcopy(DEFAULTS[k])
            else:
                db.pop(k, None)


def commit() -> bool:
    """Scrie în Supabase ce s-a schimbat. False = altcineva a scris între timp (reluăm cererea)."""
    changes = pending_changes()
    if not changes:
        return True
    res = store.commit([{"name": k, "version": _remote["versions"].get(k, 0), "data": data}
                        for k, (data, _h) in changes.items()])
    if not res.get("ok"):
        discard(changes)
        return False
    with _lock:
        for k, (_data, h) in changes.items():
            _remote["versions"][k] = res["versions"][k]
            _remote["hashes"][k] = h
    return True


def load_db():
    if use_supabase():
        # Cu Supabase nu pornim niciodată cu date goale: dacă nu răspunde, serverul nu pornește
        for attempt in range(3):
            try:
                sync_in()
                break
            except store.StoreError as err:
                if attempt == 2:
                    raise RuntimeError(f"Supabase nu răspunde ({err}). Verifică SUPABASE_URL, SUPABASE_SECRET_KEY și supabase/schema.sql.")
                time.sleep(1)
        # Prima pornire cu Supabase: mutăm automat datele locale, dacă există (doar local, nu pe Vercel)
        if not _remote["versions"] and not SERVERLESS:
            db.update(load_local())
            commit()
        return
    if not SERVERLESS:
        db.update(load_local())


def save_db():
    """Cu Supabase, scrierea se face la finalul cererii (vezi SyncMiddleware); altfel, în fișier."""
    if os.environ.get("CUTIA_PERSIST", "1") == "0" or use_supabase() or SERVERLESS:
        return
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Scriem într-un fișier temporar și apoi îl înlocuim dintr-o mișcare:
    # dacă serverul se oprește la jumătate, datele vechi rămân întregi
    tmp = DATA_FILE.with_name(f"{DATA_FILE.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA_FILE)


class SyncMiddleware:
    """Pentru fiecare cerere /api: citește ce s-a schimbat în Supabase, rulează cererea,
    scrie ce s-a schimbat. Dacă altă copie a serverului a scris între timp, reia cererea
    pe datele noi (de maxim 4 ori), ca nimic să nu se piardă."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        if SERVERLESS and not use_supabase():
            # Pe Vercel nu avem disc: fără Supabase datele s-ar pierde, deci spunem clar ce lipsește
            response = JSONResponse({"detail": msg_for(scope, "no_storage")}, status_code=503)
            return await response(scope, receive, send)
        if not use_supabase():
            return await self.app(scope, receive, send)
        body, more = b"", True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
        for attempt in range(4):
            try:
                await run_in_threadpool(sync_in)
            except store.StoreError:
                response = JSONResponse({"detail": msg_for(scope, "storage_down")}, status_code=503)
                return await response(scope, receive, send)
            sent, done, given = [], asyncio.Event(), False

            async def replay():
                nonlocal given
                if not given:
                    given = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await done.wait()
                return {"type": "http.disconnect"}

            async def capture(message):
                sent.append(message)
                if message["type"] == "http.response.body" and not message.get("more_body"):
                    done.set()

            try:
                await self.app(scope, replay, capture)
            except Exception:
                discard(list(pending_changes()))  # o eroare nu lasă date pe jumătate în memorie
                raise
            try:
                ok = await run_in_threadpool(commit)
            except store.StoreError:
                discard(list(pending_changes()))
                response = JSONResponse({"detail": msg_for(scope, "storage_down")}, status_code=503)
                return await response(scope, receive, send)
            if ok:
                for message in sent:
                    await send(message)
                return
            await asyncio.sleep(random.uniform(0.05, 0.25) * (attempt + 1))
        response = JSONResponse({"detail": msg_for(scope, "storage_busy")}, status_code=503)
        await response(scope, receive, send)


def msg_for(scope, key: str) -> str:
    """Mesajul în limba cererii (din antetul X-Lang), înainte să ajungă la language_middleware."""
    lang = dict(scope.get("headers") or []).get(b"x-lang", b"ro").decode("latin-1")
    return MESSAGES[key][ai.LANGS.index(lang) if lang in ai.LANGS else 0]


app.add_middleware(SyncMiddleware)


# Fișierele încărcate (teme, capturi Demo Day): nume aleatoriu, conținutul doar prin API
# Cu Supabase, fișierele stau în bucket-ul privat; altfel, în data/uploads.
def put_blob(content: bytes) -> str:
    stored = uuid.uuid4().hex
    if store.enabled():
        store.put_file(stored, content)
        return stored
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / stored).write_bytes(content)
    return stored


def get_blob(stored: str) -> Optional[bytes]:
    if not re.fullmatch(r"[0-9a-f]{32}", stored or ""):
        return None
    if store.enabled():
        try:
            return store.get_file(stored)
        except store.StoreError:
            return None
    path = UPLOAD_DIR / stored
    return path.read_bytes() if path.exists() else None


def delete_blob(stored: str):
    if not re.fullmatch(r"[0-9a-f]{32}", stored or ""):
        return
    if store.enabled():
        store.delete_file(stored)
    else:
        (UPLOAD_DIR / stored).unlink(missing_ok=True)


def next_id() -> int:
    value = db["next_id"]
    db["next_id"] += 1
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


load_db()

# ---------------------------------------------------------------------------
# Mod demo (CUTIA_DEMO=1): conturi și date fictive, ca aplicația să poată fi
# arătată în clasă fără conturi reale. Merge doar fără Supabase și doar pe o bază goală.
# ---------------------------------------------------------------------------

DEMO = os.environ.get("CUTIA_DEMO", "0") == "1"
DEMO_PASSWORD = "demo-cutia"
DEMO_ACCOUNTS = [
    {"login": "trainer@demo.cutia", "name": "Trainer Demo", "role": "trainer"},
    {"login": "ana", "name": "Ana Demo", "role": "student"},
    {"login": "mihai", "name": "Mihai Demo", "role": "student"},
]


def seed_demo():
    stamp = now()
    for acc in DEMO_ACCOUNTS:
        salt = secrets.token_bytes(16)
        field = "email" if acc["role"] == "trainer" else "username"
        db["users"][acc["login"]] = {"name": acc["name"], "role": acc["role"], field: acc["login"], "salt": salt.hex(),
                                     "created_at": stamp, "gen": 0, "hash": hash_password(DEMO_PASSWORD, salt)}
    ana, mihai = DEMO_ACCOUNTS[1], DEMO_ACCOUNTS[2]

    def question(author, text, category, answer=None, faq_ok=False):
        db["questions"].append({"id": next_id(), "text": text, "category": category, "anonymous": False, "faq_ok": faq_ok,
                                "author": author["name"], "author_key": author["login"], "created_at": stamp,
                                "answer": answer, "answered_at": stamp if answer else None, "ai_answer": None, "ai_answered_at": None})

    question(ana, "De ce nu se salvează formularul meu după refresh?", "debugging",
             "Datele stau doar în memoria paginii. Salvează-le în localStorage sau, dacă trebuie să le vadă și alții, într-o bază de date.", faq_ok=True)
    question(ana, "Cum îi dau lui Claude contextul întregului proiect?", "context")
    question(mihai, "Unde țin cheia API ca să nu ajungă pe GitHub?", "security",
             "Într-o variabilă de mediu, în fișierul .env, care e trecut în .gitignore. Apelul către AI se face de pe server.", faq_ok=True)

    def proposal(author, title, description, audience, voters, decision="new", note=None):
        db["proposals"].append({"id": next_id(), "title": title, "description": description, "audience": audience,
                                "author": author["name"], "author_key": author["login"], "created_at": stamp,
                                "chosen": decision == "chosen", "chosen_at": stamp if decision == "chosen" else None,
                                "decision": decision, "trainer_note": note, "voters": voters})

    proposal(ana, "Bingo de prompturi", "Un joc în care clasa bifează tehnici de prompting pe măsură ce le folosește la oră.",
             "Studenții, în timpul orei", [mihai["login"]], "discussing", "Îmi place. Facem prima versiune data viitoare?")
    proposal(mihai, "Jurnal de erori", "Fiecare student salvează erorile întâlnite și cum le-a rezolvat, ca să le găsească ușor.",
             "Studenții și trainerul", [ana["login"]], "chosen")
    proposal(ana, "Cronometru de pauze", "Un cronometru care amintește clasei să ia pauză.", "Toată clasa", [])
    save_db()


# ---------------------------------------------------------------------------
# Conturi: toată lumea intră cu email + parolă. Oricine își poate face cont
# (POST /api/register) și devine student; trainer e doar emailul din
# TRAINER_EMAILS (implicit Stoichin.radu23@gmail.com). Ca nimeni să nu-și
# însușească emailul trainerului, contul lui cere TRAINER_CODE (dacă e setat)
# sau, fără cod, merge doar cât timp nu există încă un trainer.
# Trainerul poate face și el conturi de student (utilizator + parolă).
# ---------------------------------------------------------------------------

DEFAULT_TRAINER_EMAIL = "stoichin.radu23@gmail.com"
TRAINER_EMAILS = {e.strip().lower() for e in os.environ.get("TRAINER_EMAILS", DEFAULT_TRAINER_EMAIL).split(",") if e.strip()}
REGISTRATION_OPEN = os.environ.get("CUTIA_REGISTRATION", "1") != "0"  # 0 = închizi înscrierile după ce intră clasa
MIN_PASSWORD = 8
MAX_FAILED = 5          # încercări greșite permise…
LOCK_SECONDS = 10 * 60  # …într-o fereastră de 10 minute
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_failed: dict[str, list] = {}


def hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


if DEMO and not store.enabled() and not db["users"]:
    seed_demo()


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(max_length=200)
    trainer_code: str = Field("", max_length=100)


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(max_length=200)
    trainer_code: str = Field("", max_length=100)


class LoginIn(BaseModel):
    login: Optional[str] = Field(None, max_length=200)   # emailul trainerului sau utilizatorul studentului
    email: Optional[str] = Field(None, max_length=200)   # nume vechi al câmpului, acceptat în continuare
    password: str = Field(max_length=200)


class StudentIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    password: str = Field(max_length=200)


class StudentEditIn(BaseModel):
    name: Optional[str] = Field(None, max_length=60)
    password: Optional[str] = Field(None, max_length=200)


def same(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        fail(400, "bad_email")
    return email


def clean_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        fail(400, "bad_username")
    return username


def check_password(password: str):
    if len(password or "") < MIN_PASSWORD:
        fail(400, "short_password")


def set_password(account: dict, password: str):
    salt = secrets.token_bytes(16)
    account.update(salt=salt.hex(), hash=hash_password(password, salt))
    account["gen"] = account.get("gen", 0) + 1  # sesiunile vechi ale contului se închid


def valid_trainer_code(code: Optional[str]) -> bool:
    return bool(TRAINER_CODE and code and same(code.strip(), TRAINER_CODE))


def has_trainer() -> bool:
    return any(u.get("role") == "trainer" for u in db["users"].values())


def throttle(key: str):
    """Blochează temporar contul după prea multe parole greșite."""
    recent = [t for t in _failed.get(key, []) if t > datetime.now(timezone.utc).timestamp() - LOCK_SECONDS]
    _failed[key] = recent
    if len(recent) >= MAX_FAILED:
        fail(429, "too_many_attempts")


def throttle_limit(key: str, limit: int, window: int):
    recent = [t for t in _failed.get(key, []) if t > datetime.now(timezone.utc).timestamp() - window]
    _failed[key] = recent
    if len(recent) >= limit:
        fail(429, "too_many_attempts")


def failed_attempt(key: str):
    _failed.setdefault(key, []).append(datetime.now(timezone.utc).timestamp())


# Sesiuni: tokenul e semnat de server (HMAC), deci nu trebuie scris în baza de date la
# fiecare intrare (pe Vercel, 20 de studenți care intră deodată nu se calcă pe picioare).
# „Ieși” trece tokenul pe lista de tokenuri închise; o parolă nouă le închide pe toate.

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def session_secret() -> bytes:
    explicit = os.environ.get("SESSION_SECRET", "").strip()
    if explicit:
        return explicit.encode()
    if store.enabled():
        # Derivat din cheia secretă Supabase: e deja doar pe server, deci nu mai cerem încă o variabilă
        return hashlib.sha256(b"cutia-session:" + store.secret().encode()).digest()
    with _lock:
        meta = db.setdefault("meta", {})
        if not meta.get("session_secret"):
            meta["session_secret"] = secrets.token_hex(32)
            save_db()
        return bytes.fromhex(meta["session_secret"])


def make_token(key: str, account: dict) -> str:
    expires = int(datetime.now(timezone.utc).timestamp()) + SESSION_DAYS * 86400
    payload = _b64(json.dumps({"k": key, "g": account.get("gen", 0), "x": expires, "n": secrets.token_hex(8)}).encode())
    sig = _b64(hmac.new(session_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[dict]:
    try:
        payload, sig = token.split(".")
        good = _b64(hmac.new(session_secret(), payload.encode(), hashlib.sha256).digest())
        if not same(sig, good):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return None
    if data.get("x", 0) < datetime.now(timezone.utc).timestamp():
        return None
    return data


def start_session(key: str) -> dict:
    account = db["users"][key]
    return {"token": make_token(key, account), "name": account["name"], "role": account["role"]}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    data = read_token(token) if token else None
    account = db["users"].get(data["k"]) if data else None
    if not account or account.get("gen", 0) != data.get("g") or token_hash(token) in db.get("revoked", {}):
        fail(401, "login_again")
    return {"name": account["name"], "role": account["role"], "key": data["k"]}


def require_trainer(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "trainer":
        fail(403, "trainer_only")
    return user


def require_student(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "student":
        fail(403, "student_only")
    return user


@app.get("/api/health")
def health():
    """Pentru hosting: serverul răspunde (fără date despre nimeni)."""
    return {"ok": True, "storage": "supabase" if use_supabase() else "file", "serverless": SERVERLESS}


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.post("/api/setup", status_code=201)
def setup_trainer(body: SetupIn):
    """Contul de trainer: email + parolă, creat cu codul de trainer (TRAINER_CODE)."""
    if not TRAINER_CODE:
        fail(403, "setup_off")
    throttle("setup")  # codul de trainer nu se poate ghici încercând la nesfârșit
    if not valid_trainer_code(body.trainer_code):
        failed_attempt("setup")
        fail(403, "wrong_code")
    name = body.name.strip()
    if not name:
        fail(400, "need_name")
    email = clean_email(body.email)
    if TRAINER_EMAILS and email not in TRAINER_EMAILS:
        fail(403, "not_trainer_email")
    check_password(body.password)
    with _lock:
        if email in db["users"]:
            fail(409, "email_taken")
        db["users"][email] = {"name": name, "email": email, "role": "trainer", "created_at": now(), "gen": 0}
        set_password(db["users"][email], body.password)
        save_db()
        return start_session(email)


@app.post("/api/register", status_code=201)
def register(body: RegisterIn, request: Request):
    """Cont nou cu email + parolă. Emailul trainerului → trainer; oricare altul → student."""
    name = body.name.strip()
    if not name:
        fail(400, "need_name")
    email = clean_email(body.email)
    check_password(body.password)
    is_trainer = email in TRAINER_EMAILS
    if is_trainer:
        if TRAINER_CODE:
            throttle("setup")  # codul de trainer nu se poate ghici încercând la nesfârșit
            if not body.trainer_code.strip():
                fail(428, "need_trainer_code")
            if not valid_trainer_code(body.trainer_code):
                failed_attempt("setup")
                fail(403, "wrong_code")
        elif has_trainer():
            fail(409, "email_taken")
    elif not REGISTRATION_OPEN:
        fail(403, "registration_closed")
    else:
        # Fără conturi în masă de pe aceeași adresă (20 pe oră ajung pentru o clasă)
        ip = "reg:" + (request.client.host if request.client else "?")
        throttle_limit(ip, 20, 3600)
    with _lock:
        if email in db["users"]:
            fail(409, "email_taken")
        db["users"][email] = {"name": name, "email": email, "role": "trainer" if is_trainer else "student",
                              "created_at": now(), "gen": 0}
        set_password(db["users"][email], body.password)
        save_db()
        if not is_trainer:
            failed_attempt("reg:" + (request.client.host if request.client else "?"))
        return start_session(email)


@app.post("/api/login")
def login(body: LoginIn):
    ident = (body.login or body.email or "").strip().lower()
    throttle(ident)
    account = db["users"].get(ident)
    # Același mesaj pentru utilizator greșit și parolă greșită: nu dezvăluim cine are cont
    ok = bool(account and account.get("hash")) and same(
        hash_password(body.password, bytes.fromhex(account["salt"])), account["hash"])
    if not ok:
        failed_attempt(ident)
        fail(401, "wrong_login")
    _failed.pop(ident, None)
    return start_session(ident)


@app.post("/api/students", status_code=201)
def create_student(body: StudentIn, user: dict = Depends(require_trainer)):
    """Trainerul face contul unui student: utilizator, nume afișat și parolă."""
    username = clean_username(body.username)
    name = body.name.strip()
    if not name:
        fail(400, "need_name")
    check_password(body.password)
    with _lock:
        if username in db["users"]:
            fail(409, "username_taken")
        db["users"][username] = {"name": name, "username": username, "role": "student",
                                 "created_at": now(), "created_by": user["key"], "gen": 0}
        set_password(db["users"][username], body.password)
        save_db()
    return {"key": username, "username": username, "name": name}


def student_account(student_key: str) -> dict:
    account = db["users"].get(student_key)
    if not account or account.get("role") != "student":
        fail(404, "no_student")
    return account


@app.patch("/api/students/{student_key}")
def edit_student(student_key: str, body: StudentEditIn, user: dict = Depends(require_trainer)):
    """Trainerul schimbă numele afișat sau pune o parolă nouă (studentul iese de peste tot)."""
    account = student_account(student_key)
    name = (body.name or "").strip()
    if body.name is not None and not name:
        fail(400, "need_name")
    if body.password is not None:
        check_password(body.password)
    with _lock:
        if name:
            account["name"] = name
        if body.password is not None:
            set_password(account, body.password)
        save_db()
    return {"key": student_key, "username": student_key, "name": account["name"]}


@app.delete("/api/students/{student_key}")
def delete_student(student_key: str, user: dict = Depends(require_trainer)):
    """Șterge contul (studentul nu mai poate intra). Ce a scris rămâne, cu numele lui."""
    student_account(student_key)
    with _lock:
        db["users"].pop(student_key, None)
        db["prefs"].pop(student_key, None)
        db.setdefault("push", {}).pop(student_key, None)
        save_db()
    return {"ok": True}


class PasswordIn(BaseModel):
    current: Optional[str] = Field(None, max_length=200)
    new: str = Field(max_length=200)


@app.post("/api/me/password")
def change_password(body: PasswordIn, user: dict = Depends(current_user)):
    """Schimbă parola (cu parola actuală). Celelalte dispozitive ies din cont."""
    account = db["users"].get(user["key"])
    if account is None:
        fail(401, "login_again")
    throttle(user["key"])
    if account.get("hash") and not same(hash_password(body.current or "", bytes.fromhex(account["salt"])), account["hash"]):
        failed_attempt(user["key"])
        fail(403, "wrong_current")
    check_password(body.new)
    with _lock:
        set_password(account, body.new)
        save_db()
        return {"ok": True, **start_session(user["key"])}


class ResetOut(BaseModel):
    temporary_password: str


@app.post("/api/students/{student_key}/reset-password")
def reset_password(student_key: str, user: dict = Depends(require_trainer)) -> ResetOut:
    """Trainerul generează o parolă temporară pentru un student care a uitat-o."""
    account = student_account(student_key)
    temp = secrets.token_urlsafe(9)
    with _lock:
        set_password(account, temp)
        save_db()
    return ResetOut(temporary_password=temp)


@app.post("/api/logout")
def logout(authorization: Optional[str] = Header(None)):
    token = (authorization or "").removeprefix("Bearer ").strip()
    data = read_token(token) if token else None
    if data:
        with _lock:
            stamp = datetime.now(timezone.utc).timestamp()
            revoked = {h: x for h, x in db.setdefault("revoked", {}).items() if x > stamp}  # cele expirate nu mai contează
            revoked[token_hash(token)] = data["x"]
            db["revoked"] = revoked
            save_db()
    return {"ok": True}


class PrefsIn(BaseModel):
    lang: Optional[str] = Field(None, max_length=5)
    hide_from_leaderboard: Optional[bool] = None


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    account = db["users"].get(user["key"], {})
    return {"name": user["name"], "role": user["role"], "login": user["key"], "email": account.get("email"),
            "username": account.get("username"), "has_password": bool(account.get("hash")),
            "prefs": db["prefs"].get(user["key"], {})}


@app.patch("/api/me")
def update_prefs(body: PrefsIn, user: dict = Depends(current_user)):
    with _lock:
        prefs = db["prefs"].setdefault(user["key"], {})
        if body.lang in ai.LANGS:
            prefs["lang"] = body.lang
        if body.hide_from_leaderboard is not None:
            prefs["hide_from_leaderboard"] = body.hide_from_leaderboard
        save_db()
    return {"prefs": prefs}


@app.get("/api/config")
def config():
    """Ce poate interfața: AI-ul, topicurile și dacă trainerul trebuie să-și facă întâi contul."""
    return {"ai": ai.available(), "topics": TOPICS, "needs_setup": not has_trainer(), "setup_enabled": bool(TRAINER_CODE),
            "registration": REGISTRATION_OPEN,
            "push_key": webpush.public_key() if webpush.enabled() else None, "max_upload_mb": MAX_UPLOAD_MB,
            "demo": {"accounts": DEMO_ACCOUNTS, "password": DEMO_PASSWORD} if DEMO else None}


# ---------------------------------------------------------------------------
# Întrebări: le vede doar autorul și trainerul.
# Categoriile sunt topicurile de vibe coding (textele lor stau în interfață).
# ---------------------------------------------------------------------------

TOPICS = [
    "prompting", "context", "planning", "claude-code", "artifacts", "debugging",
    "git", "security", "data", "deploy", "testing", "ai-apis", "mcp", "design", "other",
]


class QuestionIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    category: str = "other"
    anonymous: bool = False
    faq_ok: bool = False  # acordul studentului ca întrebarea să apară anonim în FAQ


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def question_view(q: dict, user: dict) -> dict:
    view = {k: v for k, v in q.items() if k != "author_key"}
    view["mine"] = q["author_key"] == user["key"]
    if user["role"] == "trainer" and q["anonymous"]:
        view["author"] = "Anonim"
    return view


@app.get("/api/categories")
def categories():
    return TOPICS


@app.get("/api/questions")
def list_questions(user: dict = Depends(current_user)):
    items = db["questions"]
    if user["role"] != "trainer":
        items = [q for q in items if q["author_key"] == user["key"]]
    return [question_view(q, user) for q in reversed(items)]


@app.post("/api/questions", status_code=201)
def ask_question(body: QuestionIn, user: dict = Depends(require_student)):
    text = body.text.strip()
    if len(text) < 3:
        fail(400, "too_short")
    with _lock:
        q = {
            "id": next_id(),
            "text": text,
            "category": body.category if body.category in TOPICS else "other",
            "anonymous": body.anonymous,
            "faq_ok": body.faq_ok,
            "author": user["name"],
            "author_key": user["key"],
            "created_at": now(),
            "answer": None,
            "answered_at": None,
            "ai_answer": None,
            "ai_answered_at": None,
        }
        db["questions"].append(q)
        save_db()
    return question_view(q, user)


def find_question(question_id: int) -> dict:
    q = next((q for q in db["questions"] if q["id"] == question_id), None)
    if not q:
        fail(404, "no_question")
    return q


@app.post("/api/questions/{question_id}/answer")
def answer_question(question_id: int, body: AnswerIn, user: dict = Depends(require_trainer)):
    with _lock:
        q = find_question(question_id)
        q["answer"] = body.text.strip()
        q["answered_at"] = now()
        save_db()
    notify([q["author_key"]], "push_answer", "questions")
    return question_view(q, user)


@app.post("/api/questions/{question_id}/ai-answer")
def ai_answer_question(question_id: int, user: dict = Depends(current_user)):
    """Răspuns rapid de la tutorul AI, cât timp studentul așteaptă trainerul.
    Se generează o singură dată per întrebare și se păstrează."""
    q = find_question(question_id)
    if user["role"] != "trainer" and q["author_key"] != user["key"]:
        fail(403, "not_yours")
    if q.get("ai_answer"):
        return question_view(q, user)
    if not ai.available():
        fail(503, "ai_off")
    answer = ai.answer_question(q["text"], q["category"], current_lang.get())
    if not answer:
        fail(502, "ai_failed")
    with _lock:
        q["ai_answer"] = answer
        q["ai_answered_at"] = now()
        save_db()
    return question_view(q, user)


class FaqConsentIn(BaseModel):
    faq_ok: bool


@app.post("/api/questions/{question_id}/faq-consent")
def set_faq_consent(question_id: int, body: FaqConsentIn, user: dict = Depends(require_student)):
    """Doar autorul decide dacă întrebarea lui poate ajunge, anonim, în FAQ.
    Dacă își retrage acordul, scoatem și intrarea din FAQ făcută din ea."""
    with _lock:
        q = find_question(question_id)
        if q["author_key"] != user["key"]:
            fail(404, "no_question")
        q["faq_ok"] = body.faq_ok
        if not body.faq_ok:
            db["faq"] = [f for f in db.get("faq", []) if f.get("question_id") != q["id"]]
        save_db()
    return question_view(q, user)


@app.post("/api/questions/{question_id}/to-faq", status_code=201)
def question_to_faq(question_id: int, user: dict = Depends(require_trainer)):
    """Trainerul publică în FAQ o întrebare cu răspuns, doar cu acordul autorului, fără nume."""
    with _lock:
        q = find_question(question_id)
        if not q.get("faq_ok"):
            fail(400, "no_faq_consent")
        if not q.get("answer"):
            fail(400, "need_answer_first")
        f = next((x for x in db.get("faq", []) if x.get("question_id") == q["id"]), None)
        if f:
            f.update(q=q["text"][:300], a=q["answer"][:3000])
        else:
            f = {"id": next_id(), "q": q["text"][:300], "a": q["answer"][:3000], "created_at": now(), "question_id": q["id"]}
            db.setdefault("faq", []).append(f)
        save_db()
    return {k: f[k] for k in ("id", "q", "a", "created_at")}


# ---------------------------------------------------------------------------
# Teme & proiecte: spațiul privat student ↔ trainer.
# Fișierele stau pe server cu nume aleatorii și se descarcă doar prin API,
# după verificarea accesului (autorul sau trainerul).
# ---------------------------------------------------------------------------

SUBMISSION_KINDS = ["homework", "project", "other"]
REVIEW_STATUSES = ["sent", "received", "reviewed", "redo"]
# „Gata când” din fișa temei
CHECKLIST = ["features", "privacy", "ai_consent", "github_readme", "no_keys", "trainer_access"]
MAX_FILES = 5
# Pe Vercel o cerere are maxim ~4,5 MB, deci toate fișierele unei predări încap în 4 MB
MAX_UPLOAD_MB = 4 if SERVERLESS else 10
MAX_FILE_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".txt", ".md",
    ".py", ".js", ".ts", ".html", ".css", ".json", ".csv", ".ipynb",
    ".docx", ".pptx", ".xlsx",
}


class ReviewIn(BaseModel):
    status: str = Field(pattern="^(received|reviewed|redo)$")
    feedback: str = Field("", max_length=4000)


def safe_filename(name: str) -> str:
    name = Path(name or "fisier").name
    name = re.sub(r"[^\w.\- ]", "_", name).strip() or "fisier"
    return name[-120:]


def submission_view(sub: dict, user: dict) -> dict:
    view = {k: v for k, v in sub.items() if k not in ("author_key", "files")}
    view["files"] = [{k: f[k] for k in ("id", "name", "size")} for f in sub["files"]]
    view["mine"] = sub["author_key"] == user["key"]
    return view


def find_submission(submission_id: int, user: dict) -> dict:
    sub = next((x for x in db["submissions"] if x["id"] == submission_id), None)
    # Pentru altcineva, o predare străină „nu există”: nu confirmăm nici că există
    if not sub or (user["role"] != "trainer" and sub["author_key"] != user["key"]):
        fail(404, "no_submission")
    return sub


@app.get("/api/submissions")
def list_submissions(user: dict = Depends(current_user)):
    items = db["submissions"]
    if user["role"] != "trainer":
        items = [x for x in items if x["author_key"] == user["key"]]
    return [submission_view(x, user) for x in reversed(items)]


@app.post("/api/submissions", status_code=201)
async def create_submission(
    kind: str = Form("homework"),
    title: str = Form("", max_length=200),
    note: str = Form("", max_length=4000),
    link: str = Form("", max_length=500),
    checklist: list[str] = Form([]),
    assignment_id: Optional[int] = Form(None),
    files: list[UploadFile] = File([]),
    user: dict = Depends(require_student),
):
    title, note, link = title.strip(), note.strip(), link.strip()
    if not title:
        fail(400, "need_title")
    if link and not re.match(r"^https?://", link, re.IGNORECASE):
        fail(400, "bad_link")
    files = [f for f in files if f.filename]
    if len(files) > MAX_FILES:
        fail(400, "too_many_files", MAX_FILES)
    if not (files or link or note):
        fail(400, "empty_submission")
    if assignment_id is not None and not any(a["id"] == assignment_id for a in db["assignments"]):
        fail(404, "no_assignment")

    # Validăm tot înainte să scriem ceva pe disc
    accepted = []
    for f in files:
        name = safe_filename(f.filename)
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            fail(400, "bad_file_type", name)
        content = await f.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            fail(400, "file_too_big", name, MAX_UPLOAD_MB)
        accepted.append((name, content))

    stored_files = []
    for name, content in accepted:
        stored = put_blob(content)
        stored_files.append({"id": uuid.uuid4().hex[:12], "name": name, "size": len(content), "stored": stored})

    with _lock:
        sub = {
            "id": next_id(),
            "kind": kind if kind in SUBMISSION_KINDS else "other",
            "title": title,
            "note": note,
            "link": link,
            "checklist": [c for c in CHECKLIST if c in checklist],
            "assignment_id": assignment_id,
            "files": stored_files,
            "author": user["name"],
            "author_key": user["key"],
            "created_at": now(),
            "status": "sent",
            "feedback": None,
            "reviewed_at": None,
        }
        db["submissions"].append(sub)
        save_db()
    return submission_view(sub, user)


@app.get("/api/submissions/{submission_id}/files/{file_id}")
def download_file(submission_id: int, file_id: str, user: dict = Depends(current_user)):
    sub = find_submission(submission_id, user)
    f = next((f for f in sub["files"] if f["id"] == file_id), None)
    content = get_blob(f["stored"]) if f else None
    if content is None:
        fail(404, "no_submission")
    # Mereu descărcare, niciodată afișat în pagină (un .html încărcat nu poate rula cod)
    return Response(content, media_type="application/octet-stream", headers={
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f['name'])}"})


@app.post("/api/submissions/{submission_id}/review")
def review_submission(submission_id: int, body: ReviewIn, user: dict = Depends(require_trainer)):
    with _lock:
        sub = find_submission(submission_id, user)
        sub["status"] = body.status
        sub["feedback"] = body.feedback.strip() or None
        sub["reviewed_at"] = now()
        save_db()
    notify([sub["author_key"]], "push_feedback", "submissions")
    return submission_view(sub, user)


# ---------------------------------------------------------------------------
# Propuneri: AI-ul retușează, studentul aprobă, apoi trimite.
# Toată clasa vede propunerile trimise și poate vota; trainerul le alege.
# ---------------------------------------------------------------------------


class ProposalDraft(BaseModel):
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    audience: str = Field("", max_length=500)


class ProposalIn(ProposalDraft):
    approved: bool = False


def is_withdrawn(p: dict) -> bool:
    return p.get("status") == "withdrawn"


DECISIONS = ["new", "discussing", "chosen", "rejected"]
REFINE_PER_DAY = max(1, int(os.environ.get("CUTIA_REFINE_PER_DAY", "20") or 20))


def decision_of(p: dict) -> str:
    return p.get("decision") or ("chosen" if p.get("chosen") else "new")


def proposal_view(p: dict, user: dict) -> dict:
    view = {k: v for k, v in p.items() if k not in ("author_key", "voters")}
    view["status"] = p.get("status", "active")
    view["decision"] = decision_of(p)
    view["votes"] = len(p["voters"])
    view["voted"] = user["key"] in p["voters"]
    view["mine"] = p["author_key"] == user["key"]
    return view


@app.post("/api/proposals/refine")
def refine_proposal(body: ProposalDraft, user: dict = Depends(require_student)):
    if not (body.title.strip() or body.description.strip() or body.audience.strip()):
        fail(400, "empty_idea")
    # Limită pe zi per student: fiecare retuș cu Claude costă (modul local e gratuit)
    left = None
    if ai.available():
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        with _lock:
            log = [t for t in db.setdefault("refine_log", {}).get(user["key"], []) if t > cutoff]
            if len(log) >= REFINE_PER_DAY:
                fail(429, "refine_limit", REFINE_PER_DAY)
            log.append(now())
            db["refine_log"][user["key"]] = log
            save_db()
        left = REFINE_PER_DAY - len(log)
    result = dict(ai.refine(body.title, body.description, body.audience, current_lang.get()))
    result["refines_left"] = left
    return result


@app.post("/api/proposals", status_code=201)
def submit_proposal(body: ProposalIn, user: dict = Depends(require_student)):
    if not body.approved:
        fail(400, "approve_first")
    fields = {k: getattr(body, k).strip() for k in ("title", "description", "audience")}
    empty = [FIELD_NAMES[k][lang_index()] for k, v in fields.items() if not v]
    if empty:
        fail(400, "missing", ", ".join(empty))
    with _lock:
        p = {
            "id": next_id(),
            **fields,
            "author": user["name"],
            "author_key": user["key"],
            "created_at": now(),
            "chosen": False,
            "decision": "new",
            "voters": [],
        }
        db["proposals"].append(p)
        save_db()
    return proposal_view(p, user)


@app.get("/api/proposals")
def list_proposals(user: dict = Depends(current_user)):
    """Clasa vede doar propunerile active; autorul și trainerul le văd și pe cele retrase."""
    return [proposal_view(p, user) for p in reversed(db["proposals"])
            if not is_withdrawn(p) or p["author_key"] == user["key"] or user["role"] == "trainer"]


def find_proposal(proposal_id: int) -> dict:
    p = next((p for p in db["proposals"] if p["id"] == proposal_id), None)
    if not p:
        fail(404, "no_proposal")
    return p


@app.post("/api/proposals/{proposal_id}/vote")
def toggle_vote(proposal_id: int, user: dict = Depends(require_student)):
    with _lock:
        p = find_proposal(proposal_id)
        if is_withdrawn(p):
            fail(400, "withdrawn")
        if p["author_key"] == user["key"]:
            fail(400, "own_vote")
        if user["key"] in p["voters"]:
            p["voters"].remove(user["key"])
        else:
            p["voters"].append(user["key"])
        save_db()
    return proposal_view(p, user)


@app.post("/api/proposals/{proposal_id}/choose")
def toggle_chosen(proposal_id: int, user: dict = Depends(require_trainer)):
    with _lock:
        p = find_proposal(proposal_id)
        if is_withdrawn(p) and not p["chosen"]:
            fail(400, "withdrawn")
        p["chosen"] = not p["chosen"]
        p["chosen_at"] = now() if p["chosen"] else None
        p["decision"] = "chosen" if p["chosen"] else "new"
        save_db()
    if p["chosen"]:
        notify([p["author_key"]], "push_chosen", "box")
    return proposal_view(p, user)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(new|discussing|chosen|rejected)$")
    note: str = Field("", max_length=500)  # nota publică a trainerului, o vede toată clasa


@app.post("/api/proposals/{proposal_id}/decision")
def set_decision(proposal_id: int, body: DecisionIn, user: dict = Depends(require_trainer)):
    """Statusul propunerii: Nouă, În discuție, Aleasă, Respinsă (+ o notă publică)."""
    with _lock:
        p = find_proposal(proposal_id)
        if is_withdrawn(p) and body.decision != decision_of(p):
            fail(400, "withdrawn")
        changed = body.decision != decision_of(p)
        was_chosen = p.get("chosen", False)
        p["decision"] = body.decision
        p["chosen"] = body.decision == "chosen"
        if p["chosen"] and not was_chosen:
            p["chosen_at"] = now()
        elif not p["chosen"]:
            p["chosen_at"] = None
        p["trainer_note"] = body.note.strip() or None
        p["decided_at"] = now()
        save_db()
    if changed:
        notify([p["author_key"]], "push_chosen" if p["chosen"] else "push_decision", "box")
    return proposal_view(p, user)


def csv_cell(value) -> str:
    """Celulele care încep cu = + - @ sunt formule în Excel: le neutralizăm."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@app.get("/api/proposals/export.csv")
def export_proposals(user: dict = Depends(require_trainer)):
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "titlu", "ce face", "cine o folosește", "autor", "voturi", "status", "retrasă", "nota trainerului", "trimisă la"])
    for p in db["proposals"]:
        w.writerow([csv_cell(x) for x in (p["id"], p["title"], p["description"], p["audience"], p["author"], len(p["voters"]),
                                          decision_of(p), "da" if is_withdrawn(p) else "", p.get("trainer_note") or "", p["created_at"])])
    # BOM ca Excel să citească diacriticele corect
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=propuneri.csv", "X-Content-Type-Options": "nosniff"})


class WithdrawIn(BaseModel):
    reason: str = Field("resolved", pattern="^(resolved|other)$")
    note: str = Field("", max_length=300)


def own_proposal(proposal_id: int, user: dict) -> dict:
    p = find_proposal(proposal_id)
    if p["author_key"] != user["key"]:
        fail(403, "not_author")
    return p


@app.post("/api/proposals/{proposal_id}/withdraw")
def withdraw_proposal(proposal_id: int, body: WithdrawIn, user: dict = Depends(require_student)):
    """Autorul își retrage propunerea (de ex. a rezolvat singur problema). Iese din cutia publică."""
    with _lock:
        p = own_proposal(proposal_id, user)
        p.update(status="withdrawn", withdrawn_reason=body.reason,
                 withdrawn_note=body.note.strip() or None, withdrawn_at=now())
        save_db()
    return proposal_view(p, user)


@app.post("/api/proposals/{proposal_id}/restore")
def restore_proposal(proposal_id: int, user: dict = Depends(require_student)):
    with _lock:
        p = own_proposal(proposal_id, user)
        p.update(status="active", withdrawn_reason=None, withdrawn_note=None, withdrawn_at=None)
        save_db()
    return proposal_view(p, user)


# ---------------------------------------------------------------------------
# Ciorne: propunerile la care încă lucrezi, salvate pe server (doar ale tale).
# ---------------------------------------------------------------------------

MAX_DRAFTS = 20


class DraftIn(BaseModel):
    title: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    audience: str = Field("", max_length=500)


def draft_view(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "owner"}


def own_draft(draft_id: int, user: dict) -> dict:
    d = next((d for d in db["drafts"] if d["id"] == draft_id), None)
    # O ciornă străină „nu există”, ca să nu confirmăm nici măcar că e acolo
    if not d or d["owner"] != user["key"]:
        fail(404, "no_draft")
    return d


@app.get("/api/drafts")
def list_drafts(user: dict = Depends(current_user)):
    mine = [d for d in db["drafts"] if d["owner"] == user["key"]]
    return [draft_view(d) for d in sorted(mine, key=lambda d: d["updated_at"], reverse=True)]


@app.post("/api/drafts", status_code=201)
def create_draft(body: DraftIn, user: dict = Depends(current_user)):
    with _lock:
        if sum(1 for d in db["drafts"] if d["owner"] == user["key"]) >= MAX_DRAFTS:
            fail(400, "too_many_drafts", MAX_DRAFTS)
        d = {"id": next_id(), "owner": user["key"], **body.model_dump(), "created_at": now(), "updated_at": now()}
        db["drafts"].append(d)
        save_db()
    return draft_view(d)


@app.put("/api/drafts/{draft_id}")
def update_draft(draft_id: int, body: DraftIn, user: dict = Depends(current_user)):
    with _lock:
        d = own_draft(draft_id, user)
        d.update(**body.model_dump(), updated_at=now())
        save_db()
    return draft_view(d)


@app.delete("/api/drafts/{draft_id}")
def delete_draft(draft_id: int, user: dict = Depends(current_user)):
    with _lock:
        d = own_draft(draft_id, user)
        db["drafts"].remove(d)
        save_db()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Mesaje directe: fiecare student are o conversație privată cu trainerul.
# Studentul vede doar conversația lui; trainerul le vede pe toate.
# ---------------------------------------------------------------------------


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def known_students() -> dict:
    """Toți studenții care au cont, după utilizator."""
    return {k: u["name"] for k, u in db["users"].items() if u.get("role") == "student"}


def thread_view(student_key: str, user: dict) -> list:
    return [
        {k: m[k] for k in ("id", "from_role", "from_name", "text", "created_at")}
        | {"mine": m["from_role"] == user["role"]}
        for m in db["messages"] if m["student_key"] == student_key
    ]


def mark_read(student_key: str, role: str):
    changed = False
    for m in db["messages"]:
        if m["student_key"] == student_key and m["from_role"] != role and not m.get(f"read_{role}"):
            m[f"read_{role}"] = True
            changed = True
    if changed:
        save_db()


def add_message(student_key: str, user: dict, text: str) -> dict:
    text = text.strip()
    if not text:
        fail(400, "too_short")
    m = {
        "id": next_id(), "student_key": student_key, "from_role": user["role"],
        "from_name": user["name"], "text": text, "created_at": now(),
        f"read_{user['role']}": True,
    }
    db["messages"].append(m)
    save_db()
    return m


@app.get("/api/dm")
def list_threads(user: dict = Depends(current_user)):
    """Student: conversația lui. Trainer: lista conversațiilor cu necitite."""
    if user["role"] == "student":
        with _lock:
            mark_read(user["key"], "student")
            return {"messages": thread_view(user["key"], user)}
    students = known_students()
    threads = []
    for key, name in students.items():
        msgs = [m for m in db["messages"] if m["student_key"] == key]
        last = msgs[-1] if msgs else None
        threads.append({
            "student_key": key, "name": name,
            "last": last["text"][:120] if last else None,
            "last_at": last["created_at"] if last else None,
            "unread": sum(1 for m in msgs if m["from_role"] == "student" and not m.get("read_trainer")),
        })
    threads.sort(key=lambda t: (t["last_at"] or "", t["name"]), reverse=True)
    return {"threads": threads}


@app.get("/api/dm/unread")
def unread_count(user: dict = Depends(current_user)):
    if user["role"] == "student":
        n = sum(1 for m in db["messages"] if m["student_key"] == user["key"]
                and m["from_role"] == "trainer" and not m.get("read_student"))
    else:
        n = sum(1 for m in db["messages"] if m["from_role"] == "student" and not m.get("read_trainer"))
    return {"unread": n}


@app.get("/api/dm/{student_key}")
def get_thread(student_key: str, user: dict = Depends(require_trainer)):
    if student_key not in known_students():
        fail(404, "no_student")
    with _lock:
        mark_read(student_key, "trainer")
        return {"name": known_students()[student_key], "messages": thread_view(student_key, user)}


@app.post("/api/dm", status_code=201)
def send_to_trainer(body: MessageIn, user: dict = Depends(require_student)):
    with _lock:
        m = add_message(user["key"], user, body.text)
    notify([k for k, u in db["users"].items() if u.get("role") == "trainer"], "push_dm", "messages")
    return thread_view(user["key"], user)[-1] if m else None


@app.post("/api/dm/{student_key}", status_code=201)
def send_to_student(student_key: str, body: MessageIn, user: dict = Depends(require_trainer)):
    if student_key not in known_students():
        fail(404, "no_student")
    with _lock:
        add_message(student_key, user, body.text)
    notify([student_key], "push_dm", "messages")
    return thread_view(student_key, user)[-1]


# ---------------------------------------------------------------------------
# Teme anunțate de trainer (cu termen și puncte) și anunțuri pentru clasă.
# ---------------------------------------------------------------------------


class AssignmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    due_at: Optional[str] = Field(None, max_length=40)
    points: int = Field(20, ge=0, le=100)


class AnnouncementIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    pinned: bool = False


def parse_due(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


@app.get("/api/assignments")
def list_assignments(user: dict = Depends(current_user)):
    out = []
    for a in reversed(db["assignments"]):
        mine = [x for x in db["submissions"] if x.get("assignment_id") == a["id"]
                and (user["role"] == "trainer" or x["author_key"] == user["key"])]
        out.append({**a, "submitted": len(mine) if user["role"] == "trainer" else bool(mine)})
    return out


@app.post("/api/assignments", status_code=201)
def create_assignment(body: AssignmentIn, user: dict = Depends(require_trainer)):
    with _lock:
        a = {"id": next_id(), "title": body.title.strip(), "description": body.description.strip(),
             "due_at": parse_due(body.due_at), "points": body.points, "created_at": now()}
        db["assignments"].append(a)
        save_db()
    notify(list(known_students()), "push_assignment", "submissions")
    return a


@app.delete("/api/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, user: dict = Depends(require_trainer)):
    with _lock:
        before = len(db["assignments"])
        db["assignments"] = [a for a in db["assignments"] if a["id"] != assignment_id]
        if len(db["assignments"]) == before:
            fail(404, "no_assignment")
        save_db()
    return {"ok": True}


@app.get("/api/announcements")
def list_announcements(user: dict = Depends(current_user)):
    return sorted(db["announcements"], key=lambda a: (a["pinned"], a["created_at"]), reverse=True)


@app.post("/api/announcements", status_code=201)
def create_announcement(body: AnnouncementIn, user: dict = Depends(require_trainer)):
    with _lock:
        a = {"id": next_id(), "text": body.text.strip(), "pinned": body.pinned,
             "author": user["name"], "created_at": now()}
        db["announcements"].append(a)
        save_db()
    return a


@app.delete("/api/announcements/{announcement_id}")
def delete_announcement(announcement_id: int, user: dict = Depends(require_trainer)):
    with _lock:
        before = len(db["announcements"])
        db["announcements"] = [a for a in db["announcements"] if a["id"] != announcement_id]
        if len(db["announcements"]) == before:
            fail(404, "no_announcement")
        save_db()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Puncte & badge-uri (calculate pe server, vezi points.py) + bonusuri.
# ---------------------------------------------------------------------------


class BonusIn(BaseModel):
    student_key: str = Field(min_length=1, max_length=60)
    points: int = Field(ge=-100, le=100)
    reason: str = Field("", max_length=200)


def points_summary(key: str, all_points: dict) -> dict:
    data = all_points.get(key, {"total": 0, "events": []})
    total = data["total"]
    return {
        "total": total,
        "level": points.level_for(total),
        "badges": points.badges(key, db, total),
        "events": sorted(data["events"], key=lambda e: e["at"] or "", reverse=True)[:30],
    }


@app.get("/api/points/me")
def my_points(user: dict = Depends(require_student)):
    return {**points_summary(user["key"], points.compute(db)), "rules": points.RULES}


@app.get("/api/points/{student_key}")
def student_points(student_key: str, user: dict = Depends(require_trainer)):
    if student_key not in known_students():
        fail(404, "no_student")
    return points_summary(student_key, points.compute(db))


@app.get("/api/leaderboard")
def leaderboard(user: dict = Depends(current_user)):
    """Public pentru clasă. Cine a ales „ascunde-mă” nu apare (dar își vede locul)."""
    all_points = points.compute(db)
    students = known_students()
    rows = []
    for key, name in students.items():
        total = all_points.get(key, {"total": 0})["total"]
        rows.append({"key": key, "name": name, "total": total, "level": points.level_for(total)["index"],
                     "hidden": db["prefs"].get(key, {}).get("hide_from_leaderboard", False)})
    rows.sort(key=lambda r: (-r["total"], r["name"].casefold()))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    visible = [r for r in rows if not r["hidden"] or user["role"] == "trainer" or r["key"] == user["key"]]
    out = []
    for r in visible[:50]:
        row = {k: r[k] for k in ("rank", "name", "total", "level")}
        row["me"] = r["key"] == user["key"]
        if user["role"] == "trainer":
            row["key"] = r["key"]
            row["hidden"] = r["hidden"]
        out.append(row)
    return out


@app.post("/api/points/bonus", status_code=201)
def give_bonus(body: BonusIn, user: dict = Depends(require_trainer)):
    if body.student_key not in known_students():
        fail(404, "no_student")
    if body.points == 0:
        fail(400, "bad_points")
    if not body.reason.strip():
        fail(400, "need_reason")
    with _lock:
        b = {"id": next_id(), "student_key": body.student_key, "points": body.points,
             "reason": body.reason.strip(), "by": user["name"], "created_at": now()}
        db["bonuses"].append(b)
        save_db()
    return b


@app.get("/api/students")
def list_students(user: dict = Depends(require_trainer)):
    all_points = points.compute(db)
    return [{"key": k, "username": k, "name": n, "total": all_points.get(k, {"total": 0})["total"]}
            for k, n in sorted(known_students().items(), key=lambda kv: kv[1].casefold())]


# ---------------------------------------------------------------------------
# AI News: știri din lumea AI, filtrate (și, cu cheie, alese de Claude).
# ---------------------------------------------------------------------------

_news_refresh = {"at": 0.0}


@app.get("/api/news")
def get_news(refresh: bool = False, user: dict = Depends(current_user)):
    import time
    # Reîmprospătare manuală cel mult o dată la 10 minute, ca să nu încărcăm sursele
    force = refresh and time.time() - _news_refresh["at"] > 600
    if force:
        _news_refresh["at"] = time.time()
    data = news.get_items(force=force)
    curated = news.curate(data["items"], current_lang.get(), ai)
    return {**data, **curated}


# ---------------------------------------------------------------------------
# Byte, robotul de știri: o dată la 24 de ore face „Briefing-ul zilei” din
# toate sursele. Rulează pe server, într-un fir separat; cheia API nu iese
# de aici. Fiecare limbă se scrie o singură dată pe zi (apoi stă în db).
# ---------------------------------------------------------------------------

DIGEST_LANGS = [l for l in os.environ.get("CUTIA_DIGEST_LANGS", "ro,en").split(",") if l in ai.LANGS]
AI_RETRY_SECONDS = 30 * 60
_digest_state = {"running": False, "manual_at": 0.0, "auto_at": 0.0}
_digest_write_lock = threading.Lock()


def make_digest(fetcher=None) -> dict:
    items, errors = news.collect(fetcher, limit=digest.SCAN_LIMIT)
    d = digest.build(items, len(news.feeds()), errors)
    first_today = not any(x["date"] == d["date"] for x in db.get("digests", []))
    with _lock:
        kept = [x for x in db.setdefault("digests", []) if x["date"] != d["date"]] + [d]
        db["digests"] = sorted(kept, key=lambda x: x["date"])[-digest.KEEP_DAYS:]
        save_db()
    for lang in DIGEST_LANGS:
        digest_view(d, lang)
    if first_today:
        notify(list(db["users"]), "push_digest", "news")
    return d


def run_digest_in_background():
    def job():
        try:
            make_digest()
        except Exception:  # o sursă sau AI-ul căzut nu oprește serverul; încercăm la următorul tur
            pass
        finally:
            _digest_state["running"] = False
    if not _digest_state["running"]:
        _digest_state["running"] = True
        if SERVERLESS:
            job()  # pe Vercel nu există fire în fundal: facem briefing-ul în cererea curentă
        else:
            threading.Thread(target=job, daemon=True).start()


def digest_view(d: dict, lang: str) -> dict:
    """Briefing-ul în limba cerută: scris de Claude (o dată) sau varianta locală."""
    import time
    with _digest_write_lock:  # mai mulți colegi deodată = tot un singur apel la Claude
        view = d["by_lang"].get(lang)
        failed_at = d.setdefault("failed", {}).get(lang, 0)
        if view is None and ai.available() and time.time() - failed_at > AI_RETRY_SECONDS:
            view = digest.write(d, lang, ai)
            with _lock:
                if view:
                    d["by_lang"][lang] = view
                else:
                    d["failed"][lang] = time.time()
                save_db()
    return view or digest.local_view(d)


def digest_loop():
    import time
    while True:
        if digest.due(db.get("digests", [])) and not _digest_state["running"]:
            run_digest_in_background()
        time.sleep(600)


def start_byte():
    if os.environ.get("CUTIA_DIGEST", "on") != "off":
        threading.Thread(target=digest_loop, daemon=True).start()


@app.get("/api/digest")
def get_digest(date: Optional[str] = None, user: dict = Depends(current_user)):
    digests = db.get("digests", [])
    d = next((x for x in digests if x["date"] == date), None) if date else (digests[-1] if digests else None)
    import time
    # Primul briefing (sau cel de azi) se face acum; dacă sursele nu merg, nu reîncercăm la fiecare vizită
    # Pe Vercel, briefing-ul îl face Vercel Cron (/api/cron/digest) sau trainerul, nu o vizită oarecare
    if not SERVERLESS and (d is None or (not date and digest.due(digests))) and time.time() - _digest_state["auto_at"] > 600:
        _digest_state["auto_at"] = time.time()
        run_digest_in_background()
    base = {"next_run": digest.next_run(), "generating": _digest_state["running"],
            "history": [x["date"] for x in reversed(digests)], "hour": digest.HOUR}
    if d is None:
        return {**base, "digest": None}
    view = digest_view(d, current_lang.get())
    return {**base, "digest": {"date": d["date"], "created_at": d["created_at"], "window_hours": d["window_hours"],
                               "stats": d["stats"], **view}}


@app.get("/api/cron/digest")
def cron_digest(authorization: Optional[str] = Header(None)):
    """Vercel Cron, o dată pe zi (vezi vercel.json). Vercel trimite CRON_SECRET ca token."""
    expected = os.environ.get("CRON_SECRET", "").strip()
    if not expected or not same((authorization or "").removeprefix("Bearer ").strip(), expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    if os.environ.get("CUTIA_DIGEST", "on") == "off":
        return {"ok": True, "skipped": True}
    if digest.due(db.get("digests", [])):
        run_digest_in_background()
    return {"ok": True}


@app.post("/api/digest/run")
def rerun_digest(user: dict = Depends(require_trainer)):
    """Trainerul cere un briefing nou acum (cel mult o dată la 10 minute)."""
    import time
    if time.time() - _digest_state["manual_at"] > 600:
        _digest_state["manual_at"] = time.time()
        run_digest_in_background()
    return {"generating": _digest_state["running"]}


# ---------------------------------------------------------------------------
# Atelier (🔒 privat): unelte pentru student. „Verifică repo-ul” citește un
# repo public de pe GitHub și verifică lista „Gata când” a trainerului.
# ---------------------------------------------------------------------------

_cooldowns: dict = {}


def cooldown(user: dict, action: str, seconds: int):
    """Limită simplă per utilizator, ca să nu consumăm GitHub/AI-ul cu click-uri repetate."""
    import time
    key = (user["key"], action)
    wait = int(_cooldowns.get(key, 0) + seconds - time.time())
    if wait > 0:
        fail(429, "slow_down", wait)
    _cooldowns[key] = time.time()


class RepoCheckIn(BaseModel):
    url: str = Field(min_length=10, max_length=300)


@app.post("/api/repo-check")
def repo_check(body: RepoCheckIn, user: dict = Depends(current_user)):
    try:
        repocheck.parse_url(body.url)
    except repocheck.RepoError:
        fail(400, "not_github")
    cooldown(user, "repo", 15)
    try:
        return repocheck.check(body.url)
    except repocheck.RepoError as err:
        fail({"not_github": 400, "not_found": 404, "github_busy": 429}.get(err.code, 502),
             {"not_found": "repo_not_found"}.get(err.code, err.code))


# ---------------------------------------------------------------- Error Doctor (privat)

MAX_IMAGE_BYTES = min(5, MAX_UPLOAD_MB) * 1024 * 1024
DOCTOR_KEEP = 20


def image_type(data: bytes) -> Optional[str]:
    """Tipul imaginii după primii octeți (nu după nume): PNG, JPEG sau WebP."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_image(upload: Optional[UploadFile]):
    if upload is None or not upload.filename:
        return None
    data = upload.file.read(MAX_IMAGE_BYTES + 1)
    kind = image_type(data)
    if len(data) > MAX_IMAGE_BYTES or not kind:
        fail(400, "bad_image", MAX_IMAGE_BYTES // (1024 * 1024))
    return kind, data


def doctor_view(e: dict) -> dict:
    return {k: e[k] for k in ("id", "created_at", "excerpt", "had_key", "ai", "result", "local", "image")}


@app.post("/api/doctor", status_code=201)
def doctor(text: str = Form("", max_length=8000), image: Optional[UploadFile] = File(None), user: dict = Depends(current_user)):
    text = text.strip()
    img = read_image(image)
    if not text and not img:
        fail(400, "need_error")
    cooldown(user, "doctor", 8)
    # Cheile lipite din greșeală nu ajung nici la Claude, nici în baza de date
    clean, had_key = tools.redact(text)
    result = tools.diagnose(clean, img, current_lang.get()) if ai.available() else None
    entry = {"id": next_id(), "author_key": user["key"], "created_at": now(), "excerpt": clean[:400], "had_key": had_key,
             "ai": bool(result), "result": result, "local": None if result else tools.local_match(clean), "image": bool(img)}
    with _lock:
        mine = [e for e in db.setdefault("doctor", []) if e["author_key"] == user["key"]]
        drop = {e["id"] for e in mine[:-(DOCTOR_KEEP - 1)]} if len(mine) >= DOCTOR_KEEP else set()
        db["doctor"] = [e for e in db["doctor"] if e["id"] not in drop] + [entry]
        save_db()
    return doctor_view(entry)


@app.get("/api/doctor")
def doctor_history(user: dict = Depends(current_user)):
    return [doctor_view(e) for e in reversed(db.get("doctor", [])) if e["author_key"] == user["key"]]


@app.delete("/api/doctor/{entry_id}")
def doctor_delete(entry_id: int, user: dict = Depends(current_user)):
    with _lock:
        before = len(db.get("doctor", []))
        db["doctor"] = [e for e in db.get("doctor", []) if not (e["id"] == entry_id and e["author_key"] == user["key"])]
        if len(db["doctor"]) == before:
            fail(404, "no_item")
        save_db()
    return {"ok": True}


# ---------------------------------------------------------------- Prompt Lab + Hall of Prompts (public)

class PromptIn(BaseModel):
    prompt: str = Field(min_length=5, max_length=6000)


@app.post("/api/prompt-lab")
def prompt_lab(body: PromptIn, user: dict = Depends(current_user)):
    cooldown(user, "prompt", 5)
    with _lock:  # pentru misiunea „Prompt Lab” (doar data, nu și promptul)
        log = db.setdefault("lab_log", {}).setdefault(user["key"], [])
        log.append(now())
        del log[:-60]
        save_db()
    clean, had_key = tools.redact(body.prompt.strip())
    result = tools.lab(clean, current_lang.get()) if ai.available() else tools.score_local(clean)
    return {**result, "had_key": had_key}


class HallIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=10, max_length=3000)
    note: str = Field("", max_length=300)


MAX_HALL_PER_USER = 30


def hall_view(h: dict, user: dict) -> dict:
    return {"id": h["id"], "title": h["title"], "prompt": h["prompt"], "note": h["note"], "author": h["author"],
            "created_at": h["created_at"], "likes": len(h["likes"]), "liked": user["key"] in h["likes"],
            "mine": h["author_key"] == user["key"]}


@app.get("/api/hall")
def hall_list(user: dict = Depends(current_user)):
    items = sorted(db.get("hall", []), key=lambda h: (len(h["likes"]), h["created_at"]), reverse=True)
    return [hall_view(h, user) for h in items]


@app.post("/api/hall", status_code=201)
def hall_add(body: HallIn, user: dict = Depends(current_user)):
    prompt, _ = tools.redact(body.prompt.strip())
    with _lock:
        if sum(h["author_key"] == user["key"] for h in db.setdefault("hall", [])) >= MAX_HALL_PER_USER:
            fail(400, "too_many_posts", MAX_HALL_PER_USER)
        h = {"id": next_id(), "author_key": user["key"], "author": user["name"], "title": body.title.strip(), "prompt": prompt,
             "note": body.note.strip(), "likes": [], "created_at": now()}
        db["hall"].append(h)
        save_db()
    return hall_view(h, user)


def find_hall(item_id: int) -> dict:
    h = next((x for x in db.get("hall", []) if x["id"] == item_id), None)
    if h is None:
        fail(404, "no_item")
    return h


@app.post("/api/hall/{item_id}/like")
def hall_like(item_id: int, user: dict = Depends(current_user)):
    with _lock:
        h = find_hall(item_id)
        if h["author_key"] == user["key"]:
            fail(400, "own_like")
        if user["key"] in h["likes"]:
            h["likes"].remove(user["key"])
        else:
            h["likes"].append(user["key"])
        save_db()
    return hall_view(h, user)


@app.delete("/api/hall/{item_id}")
def hall_delete(item_id: int, user: dict = Depends(current_user)):
    with _lock:
        h = find_hall(item_id)
        if h["author_key"] != user["key"] and user["role"] != "trainer":
            fail(403, "not_author")
        db["hall"].remove(h)
        save_db()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Ora live (🌐 public, doar cât ține ora): butonul anonim „M-am blocat”, voturi
# rapide, coada de întrebări cu upvote și biletul de ieșire. Răspunsurile la
# bilet le vede doar trainerul (și fiecare student pe al lui). Interfața
# întreabă serverul la câteva secunde (fără websocket, ca să rămână simplu).
# ---------------------------------------------------------------------------

LIVE_KEEP = 12


class LiveStartIn(BaseModel):
    title: str = Field("", max_length=120)


class PollIn(BaseModel):
    question: str = Field(min_length=2, max_length=200)
    options: list[str] = Field(max_length=4)


class VoteIn(BaseModel):
    option: int = Field(ge=0, le=3)


class LiveQuestionIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    anonymous: bool = False


class TicketIn(BaseModel):
    question: str = Field(min_length=3, max_length=300)


class TicketAnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


def live_session() -> dict:
    live = db.get("live")
    if not live:
        fail(409, "live_off")
    return live


def live_view(user: dict) -> dict:
    live = db.get("live")
    history = db.get("live_history", [])
    if not live:
        return {"active": False, "last_ended_at": history[-1]["ended_at"] if history else None}
    me, trainer = user["key"], user["role"] == "trainer"
    polls = []
    for p in live["polls"]:
        voted = me in p["votes"]
        counts = [sum(1 for v in p["votes"].values() if v == i) for i in range(len(p["options"]))]
        show = trainer or voted or not p["open"]
        polls.append({"id": p["id"], "question": p["question"], "options": p["options"], "open": p["open"],
                      "my_vote": p["votes"].get(me), "results": counts if show else None, "total": len(p["votes"])})
    queue = sorted(live["queue"], key=lambda q: (q["answered"], -len(q["upvoters"]), q["created_at"]))
    ticket = live.get("ticket")
    return {
        "active": True, "id": live["id"], "title": live["title"], "started_at": live["started_at"],
        "stuck": len(live["stuck"]), "me_stuck": me in live["stuck"], "stuck_peak": live["stuck_peak"],
        "polls": polls[::-1],
        "queue": [{"id": q["id"], "text": q["text"], "author": None if q["anonymous"] else q["author"],
                   "upvotes": len(q["upvoters"]), "upvoted": me in q["upvoters"], "mine": q["author_key"] == me,
                   "answered": q["answered"], "created_at": q["created_at"]} for q in queue],
        "ticket": None if not ticket else {
            "question": ticket["question"], "my_answer": (ticket["answers"].get(me) or {}).get("text"),
            "count": len(ticket["answers"]),
            # Biletele de ieșire le vede doar trainerul
            "answers": [{"name": a["name"], "text": a["text"], "at": a["at"]} for a in ticket["answers"].values()] if trainer else None},
    }


@app.get("/api/live")
def get_live(user: dict = Depends(current_user)):
    return live_view(user)


@app.post("/api/live/start")
def start_live(body: LiveStartIn, user: dict = Depends(require_trainer)):
    with _lock:
        if not db.get("live"):
            db["live"] = {"id": next_id(), "title": body.title.strip(), "started_at": now(), "stuck": [], "stuck_peak": 0,
                          "polls": [], "queue": [], "ticket": None}
            save_db()
    notify(list(known_students()), "push_live", "live")
    return live_view(user)


@app.post("/api/live/end")
def end_live(user: dict = Depends(require_trainer)):
    with _lock:
        live = live_session()
        live["ended_at"] = now()
        # Păstrăm ora în istoric (pentru recapitulare și misiunile săptămânii)
        db.setdefault("live_history", []).append(live)
        db["live_history"] = db["live_history"][-LIVE_KEEP:]
        db["live"] = None
        save_db()
    return live_view(user)


@app.post("/api/live/stuck")
def toggle_stuck(user: dict = Depends(require_student)):
    with _lock:
        live = live_session()
        if user["key"] in live["stuck"]:
            live["stuck"].remove(user["key"])
        else:
            live["stuck"].append(user["key"])
            live.setdefault("stuck_log", []).append({"key": user["key"], "at": now()})
        live["stuck_peak"] = max(live["stuck_peak"], len(live["stuck"]))
        save_db()
    return live_view(user)


@app.post("/api/live/stuck/reset")
def reset_stuck(user: dict = Depends(require_trainer)):
    with _lock:
        live_session()["stuck"] = []
        save_db()
    return live_view(user)


@app.post("/api/live/polls")
def create_poll(body: PollIn, user: dict = Depends(require_trainer)):
    options = [o.strip()[:80] for o in body.options if o.strip()]
    if not 2 <= len(options) <= 4:
        fail(400, "poll_options")
    with _lock:
        live = live_session()
        for p in live["polls"]:
            p["open"] = False  # un singur vot deschis odată
        live["polls"].append({"id": next_id(), "question": body.question.strip(), "options": options, "votes": {},
                              "open": True, "created_at": now()})
        save_db()
    return live_view(user)


def find_poll(live: dict, poll_id: int) -> dict:
    poll = next((p for p in live["polls"] if p["id"] == poll_id), None)
    if poll is None:
        fail(404, "no_item")
    return poll


@app.post("/api/live/polls/{poll_id}/vote")
def vote_poll(poll_id: int, body: VoteIn, user: dict = Depends(require_student)):
    with _lock:
        poll = find_poll(live_session(), poll_id)
        if not poll["open"]:
            fail(400, "poll_closed")
        if body.option >= len(poll["options"]):
            fail(400, "poll_options")
        poll["votes"][user["key"]] = body.option
        save_db()
    return live_view(user)


@app.post("/api/live/polls/{poll_id}/close")
def close_poll(poll_id: int, user: dict = Depends(require_trainer)):
    with _lock:
        find_poll(live_session(), poll_id)["open"] = False
        save_db()
    return live_view(user)


@app.post("/api/live/questions", status_code=201)
def ask_live(body: LiveQuestionIn, user: dict = Depends(current_user)):
    with _lock:
        live = live_session()
        live["queue"].append({"id": next_id(), "text": body.text.strip(), "author_key": user["key"], "author": user["name"],
                              "anonymous": body.anonymous, "upvoters": [], "answered": False, "created_at": now()})
        save_db()
    return live_view(user)


def find_live_question(live: dict, qid: int) -> dict:
    q = next((x for x in live["queue"] if x["id"] == qid), None)
    if q is None:
        fail(404, "no_item")
    return q


@app.post("/api/live/questions/{qid}/upvote")
def upvote_live(qid: int, user: dict = Depends(current_user)):
    with _lock:
        q = find_live_question(live_session(), qid)
        if q["author_key"] == user["key"]:
            fail(400, "own_vote")
        if user["key"] in q["upvoters"]:
            q["upvoters"].remove(user["key"])
        else:
            q["upvoters"].append(user["key"])
        save_db()
    return live_view(user)


@app.post("/api/live/questions/{qid}/answered")
def answered_live(qid: int, user: dict = Depends(require_trainer)):
    with _lock:
        q = find_live_question(live_session(), qid)
        q["answered"] = not q["answered"]
        save_db()
    return live_view(user)


@app.post("/api/live/ticket")
def set_ticket(body: TicketIn, user: dict = Depends(require_trainer)):
    with _lock:
        live_session()["ticket"] = {"question": body.question.strip(), "answers": {}, "created_at": now()}
        save_db()
    return live_view(user)


@app.post("/api/live/ticket/answer")
def answer_ticket(body: TicketAnswerIn, user: dict = Depends(require_student)):
    with _lock:
        ticket = live_session().get("ticket")
        if not ticket:
            fail(400, "no_ticket")
        ticket["answers"][user["key"]] = {"name": user["name"], "text": body.text.strip(), "at": now()}
        save_db()
    return live_view(user)




# ---------------------------------------------------------------- Demo Day (🌐 public)

REACTIONS = ["🔥", "👏", "💡", "🤯"]
MAX_SHOWCASE_PER_USER = 10


def clean_link(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        fail(400, "bad_link")
    return url


def showcase_view(item: dict, user: dict) -> dict:
    return {"id": item["id"], "title": item["title"], "description": item["description"], "author": item["author"],
            "live_url": item["live_url"], "repo_url": item["repo_url"], "has_image": bool(item.get("image")),
            "created_at": item["created_at"], "spotlight": item.get("spotlight", False), "mine": item["author_key"] == user["key"],
            "reactions": {e: len(item["reactions"].get(e, [])) for e in REACTIONS},
            "my_reactions": [e for e in REACTIONS if user["key"] in item["reactions"].get(e, [])]}


def find_showcase(item_id: int) -> dict:
    item = next((x for x in db.get("showcase", []) if x["id"] == item_id), None)
    if item is None:
        fail(404, "no_item")
    return item


@app.get("/api/showcase")
def list_showcase(user: dict = Depends(current_user)):
    items = sorted(db.get("showcase", []), key=lambda x: (x.get("spotlight", False), x["created_at"]), reverse=True)
    return [showcase_view(x, user) for x in items]


@app.post("/api/showcase", status_code=201)
def add_showcase(title: str = Form(..., min_length=1, max_length=120), description: str = Form("", max_length=1500),
                 live_url: str = Form("", max_length=300), repo_url: str = Form("", max_length=300),
                 image: Optional[UploadFile] = File(None), user: dict = Depends(require_student)):
    live, repo = clean_link(live_url), clean_link(repo_url)
    if not live and not repo:
        fail(400, "need_link")
    img = read_image(image)
    with _lock:
        if sum(x["author_key"] == user["key"] for x in db.setdefault("showcase", [])) >= MAX_SHOWCASE_PER_USER:
            fail(400, "too_many_posts", MAX_SHOWCASE_PER_USER)
        item = {"id": next_id(), "author_key": user["key"], "author": user["name"], "title": title.strip(),
                "description": description.strip(), "live_url": live, "repo_url": repo,
                "image": {"stored": put_blob(img[1]), "type": img[0]} if img else None,
                "reactions": {}, "spotlight": False, "created_at": now()}
        db["showcase"].append(item)
        save_db()
    return showcase_view(item, user)


@app.get("/api/showcase/{item_id}/image")
def showcase_image(item_id: int, user: dict = Depends(current_user)):
    item = find_showcase(item_id)
    content = get_blob(item["image"]["stored"]) if item.get("image") else None
    if content is None:
        fail(404, "no_item")
    # Doar PNG/JPEG/WebP verificate la încărcare; nosniff ca browserul să nu ghicească alt tip
    return Response(content, media_type=item["image"]["type"],
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


class ReactIn(BaseModel):
    emoji: str = Field(max_length=4)


@app.post("/api/showcase/{item_id}/react")
def react_showcase(item_id: int, body: ReactIn, user: dict = Depends(current_user)):
    if body.emoji not in REACTIONS:
        fail(400, "no_item")
    with _lock:
        item = find_showcase(item_id)
        if item["author_key"] == user["key"]:
            fail(400, "own_react")
        people = item["reactions"].setdefault(body.emoji, [])
        if user["key"] in people:
            people.remove(user["key"])
        else:
            people.append(user["key"])
        save_db()
    return showcase_view(item, user)


@app.post("/api/showcase/{item_id}/spotlight")
def spotlight_showcase(item_id: int, user: dict = Depends(require_trainer)):
    """Proiectul săptămânii: unul singur odată."""
    with _lock:
        item = find_showcase(item_id)
        turn_on = not item.get("spotlight")
        for x in db["showcase"]:
            x["spotlight"] = False
        item["spotlight"] = turn_on
        if turn_on:
            item["spotlight_at"] = now()
        save_db()
    return showcase_view(item, user)


@app.delete("/api/showcase/{item_id}")
def delete_showcase(item_id: int, user: dict = Depends(current_user)):
    with _lock:
        item = find_showcase(item_id)
        if item["author_key"] != user["key"] and user["role"] != "trainer":
            fail(403, "not_author")
        db["showcase"].remove(item)
        save_db()
    if item.get("image"):
        delete_blob(item["image"]["stored"])
    return {"ok": True}


# ---------------------------------------------------------------- Kickstart kit (idei alese)

@app.get("/api/proposals/{proposal_id}/kickstart")
def proposal_kickstart(proposal_id: int, user: dict = Depends(current_user)):
    p = find_proposal(proposal_id)
    if not p.get("chosen") or is_withdrawn(p):
        fail(400, "not_chosen")
    lang = current_lang.get()
    cached = db.setdefault("kickstarts", {}).get(str(proposal_id), {}).get(lang)
    if cached:
        return cached
    # O singură generare per idee și limbă; apoi o citește toată clasa din memorie
    kit = tools.kickstart(p, lang) if ai.available() else None
    if not kit:
        return {"ai": False}
    with _lock:
        db["kickstarts"].setdefault(str(proposal_id), {})[lang] = kit
        save_db()
    return kit


# ---------------------------------------------------------------- Serii, misiuni, provocarea lui Byte

class ChallengeIn(BaseModel):
    date: str = Field(min_length=10, max_length=10)


@app.post("/api/challenge")
def challenge_done(body: ChallengeIn, user: dict = Depends(require_student)):
    """Provocarea de 15 minute din briefing-ul lui Byte, bifată până la capăt."""
    try:
        day = datetime.fromisoformat(body.date).date()
    except ValueError:
        fail(400, "bad_date")
    # Doar azi sau o zi pentru care există briefing (nu în viitor, nu inventată)
    if day > points.today() or (day != points.today() and body.date not in {d["date"] for d in db.get("digests", [])}):
        fail(400, "bad_date")
    with _lock:
        days = db.setdefault("challenges", {}).setdefault(user["key"], [])
        if body.date not in days:
            days.append(body.date)
            save_db()
    return {"ok": True}


@app.get("/api/quests")
def my_quests(user: dict = Depends(require_student)):
    acts = points.activity(db).get(user["key"], [])
    week = points.week_id(points.today())
    start = points.today() - timedelta(days=points.today().weekday())
    return {"streak": points.streaks(acts), "week": week, "week_start": start.isoformat(),
            "week_end": (start + timedelta(days=6)).isoformat(), "reward": points.RULES["quest"],
            "quests": points.quest_progress(acts, week)}


# ---------------------------------------------------------------- Recap săptămânal (trainer) + FAQ (public)

class FaqIn(BaseModel):
    q: str = Field(min_length=3, max_length=300)
    a: str = Field(min_length=1, max_length=3000)
    question_id: Optional[int] = None  # dacă vine dintr-o întrebare: cere acordul autorului


def find_faq(faq_id: int) -> dict:
    f = next((x for x in db.get("faq", []) if x["id"] == faq_id), None)
    if f is None:
        fail(404, "no_item")
    return f


@app.get("/api/faq")
def list_faq(user: dict = Depends(current_user)):
    return [{k: f[k] for k in ("id", "q", "a", "created_at")} for f in db.get("faq", [])]


@app.post("/api/faq", status_code=201)
def add_faq(body: FaqIn, user: dict = Depends(require_trainer)):
    with _lock:
        if body.question_id is not None and not find_question(body.question_id).get("faq_ok"):
            fail(400, "no_faq_consent")
        f = {"id": next_id(), "q": body.q.strip(), "a": body.a.strip(), "created_at": now()}
        if body.question_id is not None:
            f["question_id"] = body.question_id
        db.setdefault("faq", []).append(f)
        save_db()
    return {k: f[k] for k in ("id", "q", "a", "created_at")}


@app.put("/api/faq/{faq_id}")
def edit_faq(faq_id: int, body: FaqIn, user: dict = Depends(require_trainer)):
    with _lock:
        f = find_faq(faq_id)
        f.update(q=body.q.strip(), a=body.a.strip())
        save_db()
    return f


@app.delete("/api/faq/{faq_id}")
def delete_faq(faq_id: int, user: dict = Depends(require_trainer)):
    with _lock:
        db["faq"].remove(find_faq(faq_id))
        save_db()
    return {"ok": True}


@app.get("/api/recap")
def weekly_recap(refresh: bool = False, user: dict = Depends(require_trainer)):
    """Ce s-a întâmplat în ultimele 7 zile + ce merită repetat + întrebări frecvente propuse."""
    from collections import Counter
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    students = known_students()
    questions = db.get("questions", [])
    new_q = [q for q in questions if q["created_at"] >= since]
    acts = points.activity(db)
    active = {k for k in students if any(at >= since[:10] for _, at in acts.get(k, []))}
    lives = [x for x in db.get("live_history", []) if x["started_at"] >= since]
    stats = {
        "questions_new": len(new_q),
        "questions_open": sum(1 for q in questions if not q.get("answer")),
        "to_review": sum(1 for x in db.get("submissions", []) if x["status"] in ("sent", "received")),
        "students": len(students), "active": len(active),
        "ideas_new": sum(1 for p in db.get("proposals", []) if p["created_at"] >= since),
        "projects_new": sum(1 for x in db.get("showcase", []) if x["created_at"] >= since),
        "live_classes": len(lives), "stuck_peak": max((x.get("stuck_peak", 0) for x in lives), default=0),
        "doctor_uses": sum(1 for x in db.get("doctor", []) if x["created_at"] >= since),
    }
    topics = Counter(q["category"] for q in new_q).most_common(5)
    inactive = sorted((students[k] for k in students if k not in active), key=str.casefold)
    answered = [q for q in questions if q.get("answer") and (q.get("answered_at") or "") >= since]
    known = {f["q"].strip().casefold() for f in db.get("faq", [])}
    # Fără AI: întrebările cu răspuns din săptămâna asta, ca propuneri de FAQ (trainerul le poate edita)
    # Doar întrebările pentru care studentul și-a dat acordul ajung propuneri de FAQ
    local_faq = [{"q": q["text"][:300], "a": q["answer"][:3000], "question_id": q["id"]} for q in answered
                 if q.get("faq_ok") and q["text"].strip().casefold() not in known][:5]

    lang = current_lang.get()
    cache_key = f"{points.week_id(points.today())}:{lang}"
    ai_part = db.setdefault("recaps", {}).get(cache_key)
    if (refresh or not ai_part) and ai.available() and (answered or new_q):
        if refresh:  # reîmprospătarea manuală, cel mult o dată pe minut
            cooldown(user, "recap", 60)
        # Doar texte, fără nume de studenți
        activity_payload = {"answered": [{"topic": q["category"], "q": q["text"][:400], "a": q["answer"][:600]} for q in answered[:20]],
                            "unanswered_topics": Counter(q["category"] for q in questions if not q.get("answer")).most_common(5),
                            "topics": topics, "numbers": stats}
        fresh = tools.recap(activity_payload, lang)
        if fresh:
            ai_part = fresh
            with _lock:
                db["recaps"][cache_key] = fresh
                save_db()
    return {"since": since, "stats": stats, "topics": [{"key": k, "count": n} for k, n in topics],
            "inactive": inactive, "ai": ai_part, "faq_suggestions": local_faq}


# ---------------------------------------------------------------------------
# Notificări push (PWA): abonamentele fiecărui utilizator (max 5 dispozitive).
# Textul notificării e generic, fără conținut privat pe ecranul blocat.
# ---------------------------------------------------------------------------

from concurrent.futures import ThreadPoolExecutor

MAX_DEVICES = 5
_push_pool = ThreadPoolExecutor(max_workers=4)


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=80, max_length=100)
    auth: str = Field(min_length=16, max_length=32)


class PushSubIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)
    keys: PushKeysIn


class PushOutIn(BaseModel):
    endpoint: str = Field(min_length=20, max_length=1000)


@app.post("/api/push/subscribe")
def push_subscribe(body: PushSubIn, user: dict = Depends(current_user)):
    if not body.endpoint.startswith("https://"):
        fail(400, "bad_subscription")
    try:
        if len(webpush.unb64u(body.keys.p256dh)) != 65 or len(webpush.unb64u(body.keys.auth)) != 16:
            raise ValueError
    except ValueError:
        fail(400, "bad_subscription")
    with _lock:
        subs = [x for x in db.setdefault("push", {}).get(user["key"], []) if x["endpoint"] != body.endpoint]
        subs.append({"endpoint": body.endpoint, "keys": body.keys.model_dump(), "at": now()})
        db["push"][user["key"]] = subs[-MAX_DEVICES:]
        save_db()
    return {"ok": True, "devices": len(db["push"][user["key"]])}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: PushOutIn, user: dict = Depends(current_user)):
    with _lock:
        db.setdefault("push", {})[user["key"]] = [x for x in db["push"].get(user["key"], []) if x["endpoint"] != body.endpoint]
        save_db()
    return {"ok": True}


def _deliver(user_key: str, sub: dict, message: dict):
    try:
        webpush.send(sub, message)
    except webpush.Gone:
        with _lock:
            db["push"][user_key] = [x for x in db["push"].get(user_key, []) if x["endpoint"] != sub["endpoint"]]
            save_db()
    except Exception:
        pass  # o notificare pierdută nu strică nimic


def notify(user_keys: list, kind: str, view: str):
    """Trimite o notificare fiecărui utilizator, în limba lui, pe toate dispozitivele abonate."""
    if not webpush.enabled():
        return
    pending = []
    for key in set(user_keys):
        lang = db["prefs"].get(key, {}).get("lang") or "ro"
        text = MESSAGES[kind][ai.LANGS.index(lang) if lang in ai.LANGS else 0]
        message = {"title": "Cutia Clasei", "body": text, "url": f"/static/index.html#{view}", "tag": kind}
        for sub in list(db.get("push", {}).get(key, [])):
            pending.append(_push_pool.submit(_deliver, key, sub, message))
    if SERVERLESS and pending:
        # Pe Vercel funcția se oprește după răspuns: așteptăm trimiterea (cel mult câteva secunde)
        from concurrent.futures import wait
        wait(pending, timeout=8)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
