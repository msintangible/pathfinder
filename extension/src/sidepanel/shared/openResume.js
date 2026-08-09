/**
 * Open a generated resume's PDF in a new browser tab. Pure utility, no
 * module-level side effects — safe to import from any screen (optimize's
 * legacy panel, review/index.js's Download resume button) without dragging
 * in a controller's own listener registrations.
 *
 * A plain tab navigation can't carry an Authorization header, so the token
 * rides along as a query param instead — see get_current_user_allow_query_token.
 */
import { getBaseUrl } from "../../shared/profileApi.js";
import { getAuthToken } from "../../shared/auth.js";

export async function openResume(downloadUrl) {
  const base = await getBaseUrl();
  const token = await getAuthToken(base);
  const url = new URL(`${base}${downloadUrl}`);
  url.searchParams.set("token", token);
  chrome.tabs.create({ url: url.toString() });
}
