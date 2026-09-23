import { contextBridge, ipcRenderer } from "electron";

export interface ScreenSource {
  id: string;
  name: string;
  thumbnail: string;
}

contextBridge.exposeInMainWorld("assistant", {
  toggle: (): void => ipcRenderer.send("toggle-visibility"),
  minimize: (): void => ipcRenderer.send("window-minimize"),
  hide: (): void => ipcRenderer.send("window-hide"),
  openExternal: (url: string): void => ipcRenderer.send("open-external", url),
  setStayMode: (on: boolean): void => ipcRenderer.send("stay-mode-set", on),
  listScreenSources: (): Promise<ScreenSource[]> =>
    ipcRenderer.invoke("list-screen-sources"),
  versions: {
    node: process.versions.node,
    chrome: process.versions.chrome,
    electron: process.versions.electron,
  },
});

declare global {
  interface Window {
    assistant: {
      toggle: () => void;
      minimize: () => void;
      hide: () => void;
      openExternal: (url: string) => void;
      setStayMode: (on: boolean) => void;
      listScreenSources: () => Promise<ScreenSource[]>;
      versions: { node: string; chrome: string; electron: string };
    };
  }
}
