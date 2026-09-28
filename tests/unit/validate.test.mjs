import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { SchemaValidator, ValidationError } from "../../protocol/validate.ts";

const load = (path) => JSON.parse(readFileSync(new URL(path, import.meta.url), "utf8"));
const validator = new SchemaValidator({
  "v1.json": load("../../protocol/schemas/v1.json"),
  "methods-v1.json": load("../../protocol/schemas/methods-v1.json"),
  "events-v1.json": load("../../protocol/schemas/events-v1.json"),
});
const fixtures = load("../../protocol/fixtures/schema-v1.json");
const bytes = (object) => new TextEncoder().encode(JSON.stringify(object));

for (const fixture of fixtures.accepted) {
  test(`schema accepted: ${fixture.name}`, () => validator.validate(fixture.value, fixture.schema));
}
for (const fixture of fixtures.rejected) {
  test(`schema rejected: ${fixture.name}`, () => {
    let check = () =>
      validator.validate(fixture.value, fixture.schema, "v1.json", fixture.expectedCode);
    if (fixture.context) {
      const response =
        fixture.schema === "warning"
          ? { jsonrpc: "2.0", method: "event.warning", params: fixture.value }
          : { jsonrpc: "2.0", id: 1, result: fixture.value };
      check = () =>
        validator.validateMessage(bytes(response), {
          pendingMethod: "bridge.hello",
          supportedMajor: fixture.context.supportedProtocolMajor,
          requiredCapabilities: fixture.context.requiredCapabilities,
          secrets: fixture.context.secrets,
        });
    }
    assert.throws(
      check,
      (error) => error instanceof ValidationError && error.code === fixture.expectedCode,
    );
  });
}

test("pre-dispatch method binding, duplicate keys, and pairing connection", () => {
  assert.throws(
    () =>
      validator.validateMessage(
        new TextEncoder().encode('{"jsonrpc":"2.0","id":1,"id":2,"result":{}}'),
      ),
    (error) => error.code === "INVALID_JSON",
  );
  assert.throws(
    () =>
      validator.validateMessage(
        bytes({ jsonrpc: "2.0", id: 1, method: "operation.execute", params: {} }),
      ),
    (error) => error.code === "INVALID_PARAMS",
  );
  assert.throws(
    () =>
      validator.validateMessage(
        bytes({ jsonrpc: "2.0", id: 1, method: "operation.nope", params: {} }),
      ),
    (error) => error.code === "METHOD_NOT_FOUND",
  );
  const approved = {
    jsonrpc: "2.0",
    id: 1,
    result: {
      pairingId: "pair1",
      trust: "full",
      expiresAt: "2026-09-23T12:00:00Z",
      sessionId: "sess1",
      credential: "a".repeat(32),
    },
  };
  assert.throws(
    () => validator.validateMessage(bytes(approved), { pendingMethod: "pair.status" }),
    (error) => error.code === "UNAUTHORIZED",
  );
  validator.validateMessage(bytes(approved), {
    pendingMethod: "pair.status",
    pairingConnection: true,
  });
});
