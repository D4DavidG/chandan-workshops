/* The "About us" panel: a button that widens into the team list.
 *
 * The animation is two CSS transitions and no JavaScript beyond flipping a
 * class. Height is animated with grid-template-rows 0fr -> 1fr, which is the
 * one way to transition to a height nobody has measured - `height: auto` does
 * not animate. See index.css.
 */
import { useState } from 'react'

const REPO = 'https://github.com/D4DavidG/SimpleBankApplicationG2'

const TEAM = [
  { name: 'Benjamin Voor', github: 'Benjamin-Voor', email: 'benjamin.a.voor@outlook.com' },
  { name: 'Daniel Tran', github: 'danieldinhtran63-hue', email: 'danieldinhtran63@gmail.com' },
  { name: 'David Gusmao', github: 'D4DavidG', email: 'davidegusmao@outlook.com' },
  { name: 'Benjamin Chermside', github: 'benchermside', email: 'bchermside@gmail.com' },
]

export default function AboutUs() {
  const [open, setOpen] = useState(false)

  return (
    <section className={open ? 'about open' : 'about'}>
      {/* A real button, so it is reachable by keyboard and announces its state.
          aria-expanded is what tells a screen reader this opens something. */}
      <button type="button" className="about-toggle lift"
              onClick={() => setOpen(!open)} aria-expanded={open}>
        About us{open ? '' : '!'}
      </button>

      <div className="about-body">
        <div>
          <ul className="team">
            {TEAM.map((person) => (
              <li key={person.github} className="card lift">
                <strong>{person.name}</strong>
                <a href={`https://github.com/${person.github}`}
                   target="_blank" rel="noreferrer">{person.github}</a>
                <a href={`mailto:${person.email}`}>{person.email}</a>
              </li>
            ))}
          </ul>
          {/* Its own layer under the people, shaped like Apply now. */}
          <a className="repo lift" href={REPO} target="_blank" rel="noreferrer">
            Project repo
          </a>
        </div>
      </div>
    </section>
  )
}
