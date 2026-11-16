import type { HandiApi } from "./contract";
import { demoApi } from "./demo";
import { liveApi } from "./live";

export const api: HandiApi = process.env.NEXT_PUBLIC_API_URL ? liveApi : demoApi;
export const IS_DEMO = api.mode === "demo";

export type * from "./contract";
