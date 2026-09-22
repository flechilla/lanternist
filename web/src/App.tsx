import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import Doctor from "./pages/Doctor";
import Library from "./pages/Library";
import NewStory from "./pages/NewStory";
import Settings from "./pages/Settings";
import Story from "./pages/Story";
import Voices from "./pages/Voices";

export default function App() {
  const [fake, setFake] = useState(false);
  useEffect(() => {
    api.health().then(
      (h) => setFake(h.fake_engines),
      () => setFake(false),
    );
  }, []);

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
          <NavLink to="/check">System check</NavLink>
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
          <Route path="/check" element={<Doctor />} />
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
