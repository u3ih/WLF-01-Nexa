/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // The default is 30s, which is shorter than a chat turn is allowed to take
    // (LLM_TIMEOUT_SECONDS defaults to 120), so a slow answer used to surface
    // as "socket hang up" instead of the reply. Kept above the backend budget.
    proxyTimeout: 180_000,
  },
  // Keeps the browser on one origin: /api/* is proxied to the FastAPI backend,
  // so no CORS setup is needed on a judge's machine.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default nextConfig;
