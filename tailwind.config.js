/** Kronus — configuração do Tailwind CSS (Seção 2.2 do plano).
 *  Build: npm run build:css  →  static/css/main.css
 */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./apps/**/*.py",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Outfit", "system-ui", "sans-serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        kronus: {
          50: "#EFF6FF", 100: "#DBEAFE", 200: "#BFDBFE", 300: "#93C5FD",
          400: "#60A5FA", 500: "#1E3A5F", 600: "#172E4A", 700: "#0F2035",
          800: "#0A1628", 900: "#060E1A",
        },
        gold: {
          50: "#FFFBEB", 100: "#FEF3C7", 200: "#FDE68A", 300: "#FCD34D",
          400: "#FBBF24", 500: "#D4A017", 600: "#B8860B", 700: "#92690A",
        },
        totem: {
          bg: "#060E1A", surface: "#0F2035", text: "#F8FAFC",
          muted: "#94A3B8", glow: "#D4A017",
        },
      },
      boxShadow: {
        glow: "0 0 24px rgba(212, 160, 23, .45)",
        "glow-idle": "0 0 18px rgba(30, 58, 95, .55)",
      },
      keyframes: {
        pulseGlow: {
          "0%, 100%": { boxShadow: "0 0 12px rgba(212,160,23,.35)" },
          "50%": { boxShadow: "0 0 28px rgba(212,160,23,.75)" },
        },
      },
      animation: { "pulse-glow": "pulseGlow 2s ease-in-out infinite" },
    },
  },
  plugins: [],
};
