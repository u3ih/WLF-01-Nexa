/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Keeps the browser on one origin: /api/* is proxied to the FastAPI backend,
  // so no CORS setup is needed on a judge's machine.
  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default nextConfig;
