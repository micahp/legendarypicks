/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#0a0a0a',
          900: '#0f0f11',
          800: '#18181b',
          700: '#27272a',
        },
        brand: {
          emerald: '#22c55e',
          neon: '#84ff00',
          punch: '#ff3d71',
        },
      },
      boxShadow: {
        card: '0 8px 24px rgba(0,0,0,0.35)',
      },
    },
  },
  plugins: [],
} 