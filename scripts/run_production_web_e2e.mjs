import { existsSync } from "node:fs";
import { lstat, readlink, symlink } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const web = resolve(root, "apps/web");
const standalone = resolve(web, ".next/standalone/apps/web");
const server = resolve(standalone, "server.js");
if (!existsSync(server) || !existsSync(resolve(web, ".next/BUILD_ID")))
  throw new Error(
    "Build @trading212/web before running the production browser fixture.",
  );

// Serve the same assets as the runtime image without duplicating the build on disk.
for (const name of [".next/static", "public"]) {
  const source = resolve(web, name);
  if (!existsSync(source)) continue;
  const destination = resolve(standalone, name);
  const target = relative(dirname(destination), source);
  const current = await lstat(destination).catch((error) => {
    if (error.code !== "ENOENT") throw error;
    return null;
  });
  if (current === null) await symlink(target, destination, "dir");
  else if (
    !current.isSymbolicLink() ||
    (await readlink(destination)) !== target
  )
    throw new Error(
      "Refusing to overwrite unexpected production fixture assets.",
    );
}

process.env.HOSTNAME = "127.0.0.1";
process.env.PORT = "3001";
await import(pathToFileURL(server).href);
