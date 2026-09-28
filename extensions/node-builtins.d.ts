// MIT. Minimal Node built-in declarations for this dependency-free package.
declare module "node:buffer" {
  export const Buffer: {
    from(bytes: Uint8Array): { toString(encoding: "base64"): string };
  };
}
declare module "node:crypto" {
  export function createHash(name: string): {
    update(bytes: Uint8Array): { digest(encoding: "hex"): string };
  };
}
declare module "node:fs" {
  interface Stats {
    size: number;
    dev: number;
    ino: number;
    mtimeMs: number;
    ctimeMs: number;
    isFile(): boolean;
    isDirectory(): boolean;
    isSymbolicLink(): boolean;
  }
  export const constants: { O_RDONLY: number; O_NOFOLLOW?: number };
  export function closeSync(fd: number): void;
  export function fstatSync(fd: number): Stats;
  export function lstatSync(path: string): Stats;
  export function openSync(path: string, flags: number): number;
  export function readdirSync(path: string): string[];
  export function readFileSync(path: string, encoding: "utf8"): string;
  export function readSync(
    fd: number,
    buffer: Uint8Array,
    offset: number,
    length: number,
    position: number,
  ): number;
  export function realpathSync(path: string): string;
}
declare module "node:os" {
  export function homedir(): string;
  export function platform(): string;
}
declare module "node:net" {
  export interface Socket {
    write(data: Uint8Array): boolean;
    destroy(): void;
    on(event: "data", listener: (chunk: Uint8Array) => void): this;
    on(event: "error", listener: (error: Error) => void): this;
    on(event: "close", listener: () => void): this;
    once(event: "connect", listener: () => void): this;
    once(event: "error", listener: (error: Error) => void): this;
    off(event: "error", listener: (error: Error) => void): this;
  }
  export function connect(options: { host: string; port: number }): Socket;
}
declare const process: {
  platform: string;
  env: Record<string, string | undefined>;
  cwd(): string;
  stdout: { write(text: string): boolean };
  pid: number;
};
declare module "node:url" {
  export function fileURLToPath(url: URL | string): string;
}
declare module "node:path" {
  export const sep: string;
  export function isAbsolute(path: string): boolean;
  export function relative(from: string, to: string): string;
  export function join(path: string, ...paths: string[]): string;
  export function resolve(path: string, ...paths: string[]): string;
}
