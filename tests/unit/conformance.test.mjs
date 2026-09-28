import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { FrameDecoder, FrameError } from "../../protocol/frame.ts";
import { decodeJson, SchemaValidator, ValidationError } from "../../protocol/validate.ts";

const load = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const framing = load("../../protocol/fixtures/framing-v1.json");
const schemaFixtures = load("../../protocol/fixtures/schema-v1.json");
const validator = new SchemaValidator({
  "v1.json": load("../../protocol/schemas/v1.json"),
  "methods-v1.json": load("../../protocol/schemas/methods-v1.json"),
  "events-v1.json": load("../../protocol/schemas/events-v1.json"),
});
const bytes = (value) => new TextEncoder().encode(JSON.stringify(value));

function typescriptOutcomes() {
  const result = { framing: {}, schema: {} };
  for (const fixture of [...framing.accepted, ...framing.rejected]) {
    const wire = Buffer.from(fixture.wireHex, "hex");
    const receiver = new FrameDecoder();
    const sizes = [
      ...(fixture.readSizes ?? []),
      wire.length - (fixture.readSizes ?? []).reduce((a, b) => a + b, 0),
    ];
    let offset = 0;
    try {
      const messages = [];
      for (const size of sizes) {
        for (const payload of receiver.feed(wire.subarray(offset, offset + size))) {
          const message = decodeJson(payload);
          validator.validate(message, "envelope", "v1.json", "INVALID_REQUEST");
          messages.push(message);
        }
        offset += size;
      }
      receiver.finish();
      result.framing[fixture.name] = messages;
    } catch (error) {
      if (error instanceof FrameError) result.framing[fixture.name] = "INVALID_FRAME";
      else if (error instanceof ValidationError) result.framing[fixture.name] = error.code;
      else throw error;
    }
  }
  for (const fixture of [...schemaFixtures.accepted, ...schemaFixtures.rejected]) {
    try {
      if (fixture.context) {
        const response =
          fixture.schema === "warning"
            ? { jsonrpc: "2.0", method: "event.warning", params: fixture.value }
            : { jsonrpc: "2.0", id: 1, result: fixture.value };
        validator.validateMessage(bytes(response), {
          pendingMethod: "bridge.hello",
          supportedMajor: fixture.context.supportedProtocolMajor,
          requiredCapabilities: fixture.context.requiredCapabilities,
          secrets: fixture.context.secrets,
        });
      } else
        validator.validate(
          fixture.value,
          fixture.schema,
          "v1.json",
          fixture.expectedCode ?? "INVALID_PARAMS",
        );
      result.schema[fixture.name] = "OK";
    } catch (error) {
      if (!(error instanceof ValidationError)) throw error;
      result.schema[fixture.name] = error.code;
    }
  }
  return result;
}

test("Python and TypeScript agree on every shared fixture outcome", () => {
  const python = spawnSync(
    process.env.PYTHON ?? "python3",
    [fileURLToPath(new URL("../prototypes/protocol_probe.py", import.meta.url))],
    {
      encoding: "utf8",
      timeout: 15_000,
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    },
  );
  assert.equal(python.status, 0, python.stderr);
  const actual = typescriptOutcomes();
  const reference = JSON.parse(python.stdout);
  assert.deepEqual(actual, reference);
  for (const fixture of [...framing.rejected])
    assert.equal(actual.framing[fixture.name], fixture.error);
  for (const fixture of schemaFixtures.rejected)
    assert.equal(actual.schema[fixture.name], fixture.expectedCode);
});
