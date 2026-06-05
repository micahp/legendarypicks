const path = require("path");

// Phase 1 = games + scores, no blockchain. Flow/FCL is off unless explicitly enabled.
const FLOW_ENABLED = process.env.NEXT_PUBLIC_ENABLE_FLOW === "true";
const FCL_STUB = path.resolve(__dirname, "config/fcl-stub.js");

/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  swcMinify: true,
  // use Next's own webpack instance (a project-level require('webpack') is a different copy and its
  // plugins won't hook the build)
  webpack: (config, { webpack, isServer }) => {
    // Add support for .cdc files
    config.module.rules.push({
      test: /\.cdc$/,
      loader: "raw-loader",
    });

    // When Flow is disabled, replace the @onflow/fcl chain with a no-op stub so its (currently broken)
    // transport-http never loads. NormalModuleReplacementPlugin rewrites the request *before* Next
    // externalizes node_modules in the server build, so it covers SSR and the client alike (a plain
    // resolve.alias only catches the client bundle). config/fcl.ts (the chain entry) is redirected too.
    // One switch for the whole chain layer; re-enable with NEXT_PUBLIC_ENABLE_FLOW=true.
    if (!FLOW_ENABLED) {
      config.plugins.push(
        new webpack.NormalModuleReplacementPlugin(/^@onflow\/fcl$/, FCL_STUB),
        new webpack.NormalModuleReplacementPlugin(/[\\/]config[\\/]fcl(\.ts)?$/, FCL_STUB)
      );
      // belt-and-suspenders: if anything still pulls these in on the server, neutralize them
      if (isServer) {
        config.resolve.alias = {
          ...(config.resolve.alias || {}),
          "@onflow/fcl": FCL_STUB,
        };
      }
    }

    return config;
  },
}
