// Loading this package must not start Blender, open a socket, or modify the workstation.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { registerBlenderExtension } from "./host.ts";

export default function blenderPi(pi: ExtensionAPI): void {
  registerBlenderExtension(pi);
}
