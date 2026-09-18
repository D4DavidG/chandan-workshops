/* Placeholder body for a page nobody has built yet.
 *
 * Delete this import and write the real page - a stub is a parking space, not a
 * component to build on. */
export default function Stub({ title, owner = 'unassigned', children }) {
  return (
    <div className="card">
      <h1>{title}</h1>
      <p className="hint">Not built yet — owner: {owner}</p>
      {children}
    </div>
  )
}
