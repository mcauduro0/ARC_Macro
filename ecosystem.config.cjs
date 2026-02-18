/**
 * PM2 Ecosystem Configuration — DigitalOcean Deployment
 * 
 * Usage:
 *   pm2 start ecosystem.config.cjs
 *   pm2 restart brlusd-dashboard
 *   pm2 logs brlusd-dashboard
 */
module.exports = {
  apps: [
    {
      name: "brlusd-dashboard",
      script: "dist/do-entry.js",
      cwd: "/opt/brlusd-dashboard",
      node_args: "--experimental-specifier-resolution=node",
      env: {
        NODE_ENV: "production",
        PORT: "3000",
      },
      // Restart policy
      max_restarts: 10,
      min_uptime: "10s",
      restart_delay: 5000,
      // Logging
      error_file: "/var/log/brlusd/error.log",
      out_file: "/var/log/brlusd/out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      merge_logs: true,
      // Memory management
      max_memory_restart: "2G",
      // Watch (disabled in production)
      watch: false,
    },
  ],
};
