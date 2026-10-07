// Limbile disponibile și datele comune ale topicurilor (iconițe, culori).
// Textele fiecărei limbi stau în i18n/<cod>.js și se încarcă la nevoie.

const LANGS = [
  { code: "ro", flag: "🇷🇴", name: "Română" },
  { code: "en", flag: "🇬🇧", name: "English" },
  { code: "fr", flag: "🇫🇷", name: "Français" },
  { code: "it", flag: "🇮🇹", name: "Italiano" },
  { code: "es", flag: "🇪🇸", name: "Español" },
  { code: "de", flag: "🇩🇪", name: "Deutsch" },
];

const TOPIC_META = {
  "prompting": {
    "icon": "💬",
    "hue": 265
  },
  "context": {
    "icon": "🧠",
    "hue": 200
  },
  "planning": {
    "icon": "🗺️",
    "hue": 35
  },
  "claude-code": {
    "icon": "⌨️",
    "hue": 20
  },
  "artifacts": {
    "icon": "🎨",
    "hue": 320
  },
  "debugging": {
    "icon": "🐛",
    "hue": 0
  },
  "git": {
    "icon": "🌿",
    "hue": 140
  },
  "security": {
    "icon": "🔐",
    "hue": 350
  },
  "data": {
    "icon": "🗄️",
    "hue": 160
  },
  "deploy": {
    "icon": "🚀",
    "hue": 210
  },
  "testing": {
    "icon": "✅",
    "hue": 95
  },
  "ai-apis": {
    "icon": "🤖",
    "hue": 280
  },
  "mcp": {
    "icon": "🔌",
    "hue": 185
  },
  "design": {
    "icon": "💅",
    "hue": 300
  },
  "other": {
    "icon": "✨",
    "hue": 50
  }
};

const I18N = {};
