import type { Config } from "@react-router/dev/config";
import { joinUrlPath } from "@plane/utils";

const basePath = joinUrlPath(process.env.VITE_SPACE_BASE_PATH ?? "", "/") ?? "/";

export default {
  appDirectory: "app",
  basename: basePath,
  // Netlify and Vercel static deployments set VITE_STATIC_DEPLOY=1. Docker
  // deployments keep SSR enabled unless they opt into the static build.
  ssr: process.env.VITE_STATIC_DEPLOY !== "1",
} satisfies Config;
