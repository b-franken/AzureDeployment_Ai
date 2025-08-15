/** @type {import('tailwindcss').Config} */

export default {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(214 32% 91%)',
        input: 'hsl(214 32% 91%)',
        ring: 'hsl(206 100% 50%)',
        background: 'hsl(0 0% 100%)',
        foreground: 'hsl(222 47% 11%)',
        primary: {
          DEFAULT: 'hsl(206 100% 50%)',
          foreground: 'hsl(0 0% 100%)'
        },
        secondary: {
          DEFAULT: 'hsl(210 40% 96%)',
          foreground: 'hsl(222 47% 11%)'
        },
        destructive: {
          DEFAULT: 'hsl(0 84% 60%)',
          foreground: 'hsl(0 0% 100%)'
        },
        muted: {
          DEFAULT: 'hsl(210 40% 96%)',
          foreground: 'hsl(215 16% 37%)'
        },
        accent: {
          DEFAULT: 'hsl(210 40% 96%)',
          foreground: 'hsl(222 47% 11%)'
        },
        card: {
          DEFAULT: 'hsl(0 0% 100%)',
          foreground: 'hsl(222 47% 11%)'
        },
        azure: {
          50: 'hsl(206 100% 97%)',
          100: 'hsl(206 100% 94%)',
          200: 'hsl(206 100% 86%)',
          300: 'hsl(206 100% 75%)',
          400: 'hsl(206 100% 61%)',
          500: 'hsl(206 100% 50%)',
          600: 'hsl(206 100% 41%)',
          700: 'hsl(206 100% 33%)',
          800: 'hsl(206 100% 27%)',
          900: 'hsl(206 100% 24%)'
        }
      },
      fontFamily: {
        sans: ['Segoe UI', 'system-ui', 'sans-serif']
      }
    }
  },
  plugins: []
}