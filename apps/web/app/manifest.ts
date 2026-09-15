import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "Portfolio Intelligence",
    short_name: "Portfolio",
    description: "Private, read-only portfolio intelligence.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#101b20",
    theme_color: "#101b20",
    icons: [
      {
        src: "/pwa/icon-192-v1.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/pwa/icon-512-v1.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/pwa/maskable-512-v1.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
