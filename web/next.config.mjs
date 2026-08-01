/** Static export: the whole site is files. No server, no database — see ADR-001. */
const nextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};
export default nextConfig;
