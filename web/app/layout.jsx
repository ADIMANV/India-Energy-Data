import { Inter, League_Gothic } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

// Two faces: League Gothic, a condensed display face, for titles and the big
// figures, set in capitals; Inter for everything you read or click.
const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const display = League_Gothic({ subsets: ["latin"], variable: "--font-display", display: "swap" });

const SITE = "https://india-energy-data.vercel.app";
const DESCRIPTION =
  "Live state-wise electricity demand, generation mix and carbon intensity for India, and every power plant by capacity and fuel.";

// What a shared link unfurls into (LinkedIn, WhatsApp, X, Slack). The image is
// app/opengraph-image.jpg, picked up by file convention; metadataBase makes
// its URL absolute, which those crawlers need.
export const metadata = {
  metadataBase: new URL(SITE),
  title: "India Electricity Data",
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    url: SITE,
    siteName: "India Electricity Data",
    title: "India Electricity Data: live demand, power plants and carbon, state by state",
    description:
      "How much power your state is using right now, which plants make it and how clean it is. " +
      "Open source, updated every 15 minutes.",
    locale: "en_IN",
  },
  twitter: { card: "summary_large_image" },
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
