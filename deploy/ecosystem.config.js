module.exports = {
  apps: [
    {
      name: "qr-verify",
      cwd: "/opt/qr_verify",
      script: "run.py",
      interpreter: "/usr/bin/python3",
      uid: "qrverify",
      gid: "qrverify",
      instances: 1,
      exec_mode: "fork",
      watch: false,
      autorestart: true,
      max_memory_restart: "300M",
      kill_timeout: 5000,
      restart_delay: 2000,
      time: true,
      error_file: "/var/log/qr_verify/pm2-error.log",
      out_file: "/var/log/qr_verify/pm2-out.log",
      env: {
        QR_VERIFY_DB: "/var/lib/qr_verify/qr_verify.sqlite3",
        QR_VERIFY_PUBLIC_KEY: "/etc/qr_verify/public.key",
        QR_VERIFY_PRODUCTS: "/etc/qr_verify/products.json",
        // While using an IP-only deployment, QR URLs use http://<ECS_PUBLIC_IP>.
        // The app itself does not need the public IP here; both values are equal,
        // so it handles the request directly instead of attempting another redirect.
        QR_VERIFY_PRINT_BASE_URL: "http://127.0.0.1:8000",
        QR_VERIFY_VERIFY_BASE_URL: "http://127.0.0.1:8000",
        QR_VERIFY_HOST: "127.0.0.1",
        QR_VERIFY_PORT: "8000",
        QR_VERIFY_STRONG_REPEAT_THRESHOLD: "3",
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
