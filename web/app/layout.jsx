import { Host_Grotesk, Instrument_Sans, Schibsted_Grotesk, Sora } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";
import FontPicker from "../components/FontPicker";

// Candidate faces for review — one survives; FontPicker switches between them.
const host = Host_Grotesk({ subsets: ["latin"], variable: "--f-host", display: "swap" });
const instrument = Instrument_Sans({ subsets: ["latin"], variable: "--f-instrument", display: "swap" });
const sora = Sora({ subsets: ["latin"], variable: "--f-sora", display: "swap" });
const schibsted = Schibsted_Grotesk({ subsets: ["latin"], variable: "--f-schibsted", display: "swap" });

export const metadata = {
  title: "India Electricity Data",
  description:
    "Live state-wise electricity demand, generation mix and carbon intensity for India, and every power plant by capacity and fuel.",
};

export default function RootLayout({ children }) {
  return (
    <html
      lang="en"
      className={`${host.variable} ${instrument.variable} ${sora.variable} ${schibsted.variable}`}
    >
      <body>
        {children}
        <FontPicker />
      </body>
    </html>
  );
}
