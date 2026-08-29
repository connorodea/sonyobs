import { app, safeStorage } from "electron";
import { promises as fs } from "node:fs";
import path from "node:path";

export interface StoredKeys {
  openRouterKey?: string;
  deepgramKey?: string;
}

const FIELDS = ["openRouterKey", "deepgramKey"] as const;

function secretsPath(): string {
  return path.join(app.getPath("userData"), "secrets.json");
}

async function readDisk(): Promise<string> {
  try {
    return await fs.readFile(secretsPath(), "utf8");
  } catch {
    return "";
  }
}

async function writeDisk(content: string): Promise<void> {
  const file = secretsPath();
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, content, { mode: 0o600 });
}

function parseKeys(raw: string): StoredKeys {
  if (raw.startsWith("enc:")) {
    if (!safeStorage.isEncryptionAvailable()) return {};
    try {
      const decrypted = safeStorage.decryptString(Buffer.from(raw.slice(4), "base64"));
      const parsed = JSON.parse(decrypted) as Partial<Record<string, unknown>>;
      const out: StoredKeys = {};
      for (const field of FIELDS) {
        const value = parsed[field];
        if (typeof value === "string" && value.trim() !== "") {
          out[field] = value.trim();
        }
      }
      return out;
    } catch {
      return {};
    }
  }
  return {};
}

async function loadKeys(): Promise<StoredKeys> {
  const raw = await readDisk();
  if (raw.trim() === "") return {};
  return parseKeys(raw);
}

export async function storeKeys(input: StoredKeys): Promise<StoredKeys> {
  const prev = await loadKeys();
  const merged: StoredKeys = { ...prev };
  for (const field of FIELDS) {
    const value = input[field];
    if (value !== undefined) {
      const trimmed = value.trim();
      if (trimmed === "") {
        delete merged[field];
      } else {
        merged[field] = trimmed;
      }
    }
  }
  const blob = "enc:" + safeStorage.encryptString(JSON.stringify(merged)).toString("base64");
  await writeDisk(blob);
  return merged;
}

export const openRouterHandlers = {
  async getStoredKeys(): Promise<StoredKeys> {
    return loadKeys();
  },
  async setStoredKeys(keys: StoredKeys): Promise<StoredKeys> {
    return storeKeys(keys);
  },
  async clearKeys(): Promise<StoredKeys> {
    await writeDisk("");
    return {};
  },
};
