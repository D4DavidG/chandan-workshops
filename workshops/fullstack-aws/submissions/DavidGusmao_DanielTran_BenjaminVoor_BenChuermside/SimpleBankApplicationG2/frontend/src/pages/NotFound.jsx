import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="card narrow">
      <h1>Page not found</h1>
      <p><Link to="/">Back to your accounts</Link></p>
    </div>
  )
}
