import { contextBridge, ipcRenderer } from "electron";

export interface StoredKeysInput {
  openRouterKey?: string;
  deepgramKey?: string;
}

export interface ServiceStatusView {
  running: boolean;
  port: number;
  detail: string;
}

export interface KeysPresent {
  openRouter: boolean;
  deepgram: boolean;
}

function keysToPresent(keys: { openRouterKey?: string; deepgramKey?: string }): KeysPresent {
  return {
    openRouter: Boolean(keys.openRouterKey),
    deepgram: Boolean(keys.deepgramKey),
  };
}

const api = {
  health: (): Promise<unknown> => ipcRenderer.invoke("capture:health"),
  status: (): Promise<unknown> => ipcRenderer.invoke("capture:status"),
  profiles: (): Promise<unknown> => ipcRenderer.invoke("capture:profiles"),
  scenes: (): Promise<unknown> => ipcRenderer.invoke("capture:scenes"),
  sources: (): Promise<unknown> => ipcRenderer.invoke("capture:sources"),
  sonyScan: (): Promise<unknown> => ipcRenderer.invoke("capture:sonyScan"),
  start: (profile: string): Promise<unknown> => ipcRenderer.invoke("capture:start", profile),
  stop: (): Promise<unknown> => ipcRenderer.invoke("capture:stop"),
  pause: (): Promise<unknown> => ipcRenderer.invoke("capture:pause"),
  resume: (): Promise<unknown> => ipcRenderer.invoke("capture:resume"),

  onSidecarState: (cb: (state: string) => void): void =>
    void ipcRenderer.on("sidecar:state", (_event, state: string) => cb(state)),

  getKeysPresent: (): Promise<KeysPresent> =>
    ipcRenderer.invoke("settings:getKeys").then((keys: { openRouterKey?: string; deepgramKey?: string }) => keysToPresent(keys)),

  saveKey: (which: "openRouterKey" | "deepgramKey", value: string): Promise<KeysPresent> =>
    ipcRenderer.invoke("settings:setKeys", { [which]: value } as Record<string, string>).then(
      (keys: { openRouterKey?: string; deepgramKey?: string }) => keysToPresent(keys),
    ),

  clearKeys: (): Promise<KeysPresent> =>
    ipcRenderer.invoke("settings:clearKeys").then(
      (keys: { openRouterKey?: string; deepgramKey?: string }) => keysToPresent(keys),
    ),

  servicesStatus: (): Promise<Record<string, ServiceStatusView>> =>
    ipcRenderer.invoke("services:status"),

  serviceStart: (id: string): Promise<ServiceStatusView> =>
    ipcRenderer.invoke("services:start", id),

  serviceStop: (id: string): Promise<void> =>
    ipcRenderer.invoke("services:stop", id),

  runFabric: (pattern: string, prompt: string): Promise<{ ok: boolean; output?: string; error?: string }> =>
    ipcRenderer.invoke("edit:runFabric", pattern, prompt),
  cutroomStatus: (): Promise<{ available: boolean; health?: string; keyPresent?: boolean; detail?: string }> =>
    ipcRenderer.invoke("edit:cutroomStatus"),
  runCutroom: (prompt: string): Promise<{ ok: boolean; output?: string; error?: string }> =>
    ipcRenderer.invoke("edit:runCutroom", prompt),
};

contextBridge.exposeInMainWorld("sonyobs", api);

export type SonyOBSApi = typeof api;