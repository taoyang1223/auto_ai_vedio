import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172033",
        mist: "#f4f7f8",
        line: "#dde5e7",
        teal: {
          650: "#10746b"
        }
      },
      boxShadow: {
        panel: "0 10px 30px rgba(20, 35, 45, 0.07)"
      }
    }
  },
  plugins: []
} satisfies Config;
