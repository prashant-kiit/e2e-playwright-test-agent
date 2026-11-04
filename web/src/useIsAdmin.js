import { useEffect, useState } from "react";
import { api } from "./api.js";

/**
 * Whether the signed-in operator is a tenant admin.
 *
 * **Presentation only.** The server's admin dependency is what enforces the
 * tenant-admin actions (P5-13's quota write, P5-14's user administration); this
 * decides whether to *offer* them. A hidden control is a tidier portal, not a
 * permission, which is why both panels still render a refusal rather than
 * treating one as impossible.
 *
 * One hook rather than the same four lines in each page. It was copied into
 * `Projects.jsx` and then `Settings.jsx`, and the comment in the first one
 * saying "read here rather than threaded down from App, because this is the
 * only page that wants it" had already stopped being true by the second --
 * which is the usual way a duplicated fetch announces itself.
 *
 * `false` on failure, deliberately: not knowing the role hides a panel, and a
 * page that refused to render because a role probe failed would be trading the
 * thing the operator came for against one they may not even be entitled to.
 * `App.jsx` already calls `api.me()` for the session check and throws the role
 * away; threading it down from there would mean a context for one boolean, and
 * the call is cheap and cached by the browser for the life of the page.
 */
export function useIsAdmin() {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .me()
      .then((who) => live && setIsAdmin(who.role === "admin"))
      .catch(() => live && setIsAdmin(false));
    return () => {
      live = false;
    };
  }, []);
  return isAdmin;
}
