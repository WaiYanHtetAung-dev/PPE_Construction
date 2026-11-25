import { writeFileSync } from "node:fs";
import { preview } from "vite";

const server = await preview({
  preview: { host: "127.0.0.1", port: 0, strictPort: true },
});
writeFileSync(process.argv[2], String(server.httpServer.address().port), { flag: "wx" });
