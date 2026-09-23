import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, type Me } from "./api";
import { useAction, useOptions } from "./hooks";
import Doctor from "./pages/Doctor";
import Library from "./pages/Library";
import NewStory from "./pages/NewStory";
import Settings from "./pages/Settings";
import SignIn from "./pages/SignIn";
import Story from "./pages/Story";
import Voices from "./pages/Voices";

export default function App() {
  const opts = useOptions();
  const fake = opts?.fake_engines ?? false;
  // The hosted edition has no machine of the user's to check.
  const local = opts?.edition === "local";
  const hosted = opts?.edition === "hosted";
  // Hosted: who is signed in; null when no one is, undefined until we know.
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const { pathname } = useLocation();
  const { busy, error, run } = useAction();
  useEffect(() => {
    if (hosted) api.me().then(setMe, () => setMe(null));
  }, [hosted]);

  async function signOut() {
    const { url } = await api.signOut();
    location.assign(url);
  }

  // Until the edition (and, hosted, who's signed in) is known, a page would ask the API as the wrong one.
  if (!opts || (hosted && me === undefined)) return null;
  if (hosted && me === null && pathname !== "/sign-in") return <Navigate to="/sign-in" replace />;
  if (hosted && me && pathname === "/sign-in") return <Navigate to="/" replace />;

  return (
    <>
      <header className="topbar">
        <Link to="/" className="wordmark" aria-label="Lanternist, your stories">
          <i className="lens" aria-hidden="true" />
          <span>Lanternist</span>
        </Link>
        {(!hosted || me) && (
          <nav className="nav" aria-label="Main">
            <NavLink to="/" end>
              Stories
            </NavLink>
            <NavLink to="/new">New story</NavLink>
            <NavLink to="/voices">Voices</NavLink>
            {local && <NavLink to="/check">System check</NavLink>}
            <NavLink to="/settings">Settings</NavLink>
          </nav>
        )}
        {hosted && me && (
          <div className="account">
            <span>{me.email}</span>
            <button className="quiet small" type="button" disabled={busy} onClick={() => void run(signOut)}>
              Sign out
            </button>
            {error && <span className="error">{error}</span>}
          </div>
        )}
      </header>
      {fake && (
        <div className="testmode" role="status">
          <b>Test mode.</b>
          <span>
            Every model is replaced by test patterns and tones, so films render in seconds and show nothing
            real.
          </span>
        </div>
      )}
      <main>
        {hosted && me === null ? (
          <SignIn />
        ) : (
          <Routes>
            <Route path="/" element={<Library />} />
            <Route path="/new" element={<NewStory />} />
            <Route path="/stories/:id" element={<Story />} />
            <Route path="/stories/:id/:step" element={<Story />} />
            <Route path="/voices" element={<Voices />} />
            {local && <Route path="/check" element={<Doctor />} />}
            <Route path="/settings" element={<Settings />} />
            <Route
              path="*"
              element={
                <p>
                  There is nothing at this address. <Link to="/">Go to your stories</Link>.
                </p>
              }
            />
          </Routes>
        )}
      </main>
    </>
  );
}
