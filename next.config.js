/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  swcMinify: true,
  webpack: (config) => {
    // Add support for .cdc files
    config.module.rules.push({
      test: /\.cdc$/,
      loader: "raw-loader",
    });

    return config;
  },
}
