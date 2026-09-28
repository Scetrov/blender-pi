/** Bounded, dependency-free subset of JSON Schema used by the version-1 protocol. */
export type Schema = Record<string, unknown>;
export type SchemaSet = Record<string, Schema>;
const MAX_DEPTH = 64;
const MAX_WIRE_BYTES = 1_048_576;

export class ValidationError extends Error {
  readonly code: string;
  constructor(code = "INVALID_PARAMS") {
    super(code);
    this.name = "ValidationError";
    this.code = code;
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sortedJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(sortedJson).join(",")}]`;
  if (record(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${sortedJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

/** JSON.parse silently accepts duplicate keys; scan the already parsed grammar to reject them. */
function rejectDuplicateKeys(text: string): void {
  let position = 0;
  const whitespace = () => {
    while (/\s/.test(text[position] ?? "") && position < text.length) position++;
  };
  const stringToken = (): string => {
    const start = position++;
    while (position < text.length) {
      if (text[position] === "\\") {
        position += 2;
      } else if (text[position++] === '"') {
        return JSON.parse(text.slice(start, position));
      }
    }
    throw new ValidationError("INVALID_JSON");
  };
  const value = (depth: number): void => {
    if (depth > MAX_DEPTH) throw new ValidationError("INVALID_JSON");
    whitespace();
    const leading = text[position];
    if (leading === '"') {
      stringToken();
    } else if (leading === "{" || leading === "[") {
      const object = leading === "{";
      position++;
      whitespace();
      const keys = new Set<string>();
      while (text[position] !== (object ? "}" : "]")) {
        if (object) {
          const key = stringToken();
          if (keys.has(key)) throw new ValidationError("INVALID_JSON");
          keys.add(key);
          whitespace();
          position++; // colon; grammar was checked by JSON.parse.
        }
        value(depth + 1);
        whitespace();
        if (text[position] !== ",") break;
        position++;
        whitespace();
      }
      position++;
    } else {
      while (position < text.length && !/[\s,}\]]/.test(text[position])) position++;
    }
  };
  value(0);
}

export function decodeJson(payload: Uint8Array): unknown {
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(payload);
    const parsed: unknown = JSON.parse(text);
    rejectDuplicateKeys(text);
    return parsed;
  } catch (error) {
    if (error instanceof ValidationError) throw error;
    throw new ValidationError("INVALID_JSON");
  }
}

function matchesType(value: unknown, expected: string): boolean {
  switch (expected) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "integer":
      return typeof value === "number" && Number.isSafeInteger(value);
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "string":
      return typeof value === "string";
    case "array":
      return Array.isArray(value);
    case "object":
      return record(value);
    default:
      throw new ValidationError("INTERNAL_ERROR");
  }
}

export class SchemaValidator {
  private readonly schemas: SchemaSet;
  constructor(schemas: SchemaSet) {
    this.schemas = schemas;
  }

  private check(value: unknown, schema: Schema, source: string, depth: number): boolean {
    if (depth > MAX_DEPTH) return false;
    if (typeof schema.$ref === "string") {
      const [file, definition] = schema.$ref.split("#/$defs/");
      const resolved = (
        this.schemas[file || source]?.$defs as Record<string, Schema> | undefined
      )?.[definition];
      if (!resolved) throw new ValidationError("INTERNAL_ERROR");
      if (!this.check(value, resolved, file || source, depth + 1)) return false;
    }
    if (schema.type !== undefined) {
      const types = Array.isArray(schema.type) ? schema.type : [schema.type];
      if (!types.some((type) => matchesType(value, String(type)))) return false;
    }
    if (
      schema.const !== undefined &&
      (typeof value !== typeof schema.const || value !== schema.const)
    )
      return false;
    if (
      Array.isArray(schema.enum) &&
      !schema.enum.some((item) => typeof item === typeof value && item === value)
    )
      return false;
    if (
      Array.isArray(schema.required) &&
      (!record(value) || schema.required.some((key) => !(String(key) in value)))
    )
      return false;
    if (
      Array.isArray(schema.oneOf) &&
      schema.oneOf.filter((option) => this.check(value, option as Schema, source, depth + 1))
        .length !== 1
    )
      return false;
    if (record(value)) {
      if (
        typeof schema.maxProperties === "number" &&
        Object.keys(value).length > schema.maxProperties
      )
        return false;
      const properties = (schema.properties ?? {}) as Record<string, Schema>;
      for (const [key, item] of Object.entries(value)) {
        if (key in properties) {
          if (!this.check(item, properties[key], source, depth + 1)) return false;
        } else if (schema.additionalProperties === false) return false;
        else if (
          record(schema.additionalProperties) &&
          !this.check(item, schema.additionalProperties, source, depth + 1)
        )
          return false;
      }
    }
    if (Array.isArray(value)) {
      if (typeof schema.minItems === "number" && value.length < schema.minItems) return false;
      if (typeof schema.maxItems === "number" && value.length > schema.maxItems) return false;
      if (schema.uniqueItems && new Set(value.map(sortedJson)).size !== value.length) return false;
      if (
        record(schema.items) &&
        value.some((item) => !this.check(item, schema.items as Schema, source, depth + 1))
      )
        return false;
    }
    if (typeof value === "string") {
      if (typeof schema.minLength === "number" && [...value].length < schema.minLength)
        return false;
      if (typeof schema.maxLength === "number" && [...value].length > schema.maxLength)
        return false;
      if (typeof schema.pattern === "string" && !new RegExp(schema.pattern).test(value))
        return false;
      if (
        schema.format === "date-time" &&
        (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
          Number.isNaN(Date.parse(value)))
      )
        return false;
    }
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return false;
      if (typeof schema.minimum === "number" && value < schema.minimum) return false;
      if (typeof schema.maximum === "number" && value > schema.maximum) return false;
      if (typeof schema.exclusiveMinimum === "number" && value <= schema.exclusiveMinimum)
        return false;
      if (typeof schema.exclusiveMaximum === "number" && value >= schema.exclusiveMaximum)
        return false;
    }
    return true;
  }

  validate(value: unknown, definition: string, source = "v1.json", code = "INVALID_PARAMS"): void {
    const schema = (this.schemas[source]?.$defs as Record<string, Schema> | undefined)?.[
      definition
    ];
    if (!schema) throw new ValidationError("INTERNAL_ERROR");
    if (!this.check(value, schema, source, 0)) throw new ValidationError(code);
  }

  validateMessage(
    payload: Uint8Array,
    options: {
      pendingMethod?: string;
      supportedMajor?: number;
      requiredCapabilities?: string[];
      secrets?: string[];
      pairingConnection?: boolean;
    } = {},
  ): Record<string, unknown> {
    if (payload.byteLength > MAX_WIRE_BYTES) throw new ValidationError("INVALID_FRAME");
    const message = decodeJson(payload);
    this.validate(message, "envelope", "v1.json", "INVALID_REQUEST");
    if (!record(message)) throw new ValidationError("INVALID_REQUEST");
    const methods = this.schemas["methods-v1.json"];
    if ("method" in message && "id" in message) {
      if (!this.check(message, methods, "methods-v1.json", 0)) {
        const results = methods["x-results"] as Record<string, string>;
        throw new ValidationError(
          typeof message.method === "string" && message.method in results
            ? "INVALID_PARAMS"
            : "METHOD_NOT_FOUND",
        );
      }
    } else if ("method" in message) {
      if (!this.check(message, this.schemas["events-v1.json"], "events-v1.json", 0))
        throw new ValidationError("INVALID_PARAMS");
    } else if ("result" in message) {
      const target = (methods["x-results"] as Record<string, string>)[options.pendingMethod ?? ""];
      if (!target) throw new ValidationError("INVALID_REQUEST");
      this.validate(message.result, target.split("#/$defs/")[1]);
      if (options.pendingMethod === "bridge.hello") {
        const result = message.result as Record<string, unknown>;
        if (Number(String(result.protocolVersion).split(".")[0]) !== (options.supportedMajor ?? 1))
          throw new ValidationError("UNSUPPORTED_VERSION");
        if (
          !(options.requiredCapabilities ?? []).every((capability) =>
            (result.capabilities as string[]).includes(capability),
          )
        )
          throw new ValidationError("MISSING_CAPABILITY");
      }
      if (
        options.pendingMethod === "pair.status" &&
        record(message.result) &&
        "credential" in message.result &&
        !options.pairingConnection
      )
        throw new ValidationError("UNAUTHORIZED");
    }
    if (
      ("result" in message || "error" in message || ("method" in message && !("id" in message))) &&
      (options.secrets ?? []).some((secret) => secret && JSON.stringify(message).includes(secret))
    )
      throw new ValidationError("INVALID_PARAMS");
    return message;
  }
}
