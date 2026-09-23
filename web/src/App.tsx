import { Link, NavLink, Route, Routes } from "react-router-dom";
import { useOptions } from "./hooks";
import Doctor from "./pages/Doctor";
import Library from "./pages/Library";
import NewStory from "./pages/NewStory";
import Settings from "./pages/Settings";
import Story from "./pages/Story";
import Voices from "./pages/Voices";

export default function App() {
  const opts = useOptions();
  const fake = opts?.fake_engines ?? false;
  // The hosted edition has no machine of the user's to check.
  const local = opts?.edition === "local";

  return (
    <>
      <header className="topbar">
        <Link to="/" className="wordmark" aria-label="Lanternist, your stories">
          <i className="lens" aria-hidden="true" />
          <span>Lanternist</span>
        </Link>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            Stories
          </NavLink>
          <NavLink to="/new">New story</NavLink>
          <NavLink to="/voices">Voices</NavLink>
          {local && <NavLink to="/check">System check</NavLink>}
          <NavLink to="/settings">Settings</NavLink>
        </nav>
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
      </main>
    </>
  );
}
