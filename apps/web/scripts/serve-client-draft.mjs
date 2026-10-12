import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const file = fileURLToPath(new URL("../../../build/client-draft/Dhanadhara-Client-Draft.html", import.meta.url));
const html = await readFile(file);
const port = Number(process.env.PORT ?? 3001);
const server = createServer((request, response) => {
  if (!["GET", "HEAD"].includes(request.method)) { response.writeHead(405); response.end(); return; }
  if (request.url !== "/" && request.url !== "/index.html") { response.writeHead(404); response.end(); return; }
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" });
  response.end(request.method === "HEAD" ? undefined : html);
});
server.listen(port, "127.0.0.1", () => console.log(`Public client draft: http://localhost:${port}`));
