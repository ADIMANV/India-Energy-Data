import { Schibsted_Grotesk } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

// One face for everything — interface, headings, long-form pages and figures
// (tabular numerals where columns of numbers need to line up).
const sans = Schibsted_Grotesk({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export const metadata = {
  title: "India Electricity Data",
  description:
    "Live state-wise electricity demand, generation mix and carbon intensity for India, and every power plant by capacity and fuel.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={sans.variable}>
      <body>{children}</body>
    </html>
  );
}
