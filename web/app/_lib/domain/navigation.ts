import type { ViewKey } from "./types";

/** Retired or unknown bookmarks always open the article library. */
export function viewFromHash(hash = ""): ViewKey {
  const view = hash.replace(/^#\/?/, "");
  return view === "all" || view === "selected" || view === "company" ? view : "all";
}
