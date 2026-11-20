import { Inter, League_Gothic } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

// Two faces: League Gothic, a condensed display face, for titles and the big
// figures, set in capitals; Inter for everything you read or click.
const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const display = League_Gothic({ subsets: ["latin"], variable: "--font-display", display: "swap" });

export const metadata = {
  title: "India Electricity Data",
  description:
    "Live state-wise electricity demand, generation mix and carbon intensity for India, and every power plant by capacity and fuel.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
