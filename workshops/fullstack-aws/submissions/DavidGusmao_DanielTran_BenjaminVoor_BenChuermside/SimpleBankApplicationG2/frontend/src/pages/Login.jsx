import { useNavigate } from 'react-router-dom'
import LoginForm from '../components/LoginForm'

export default function Login() {
  const navigate = useNavigate()
  return (
    <div className="card narrow">
      <h1>Sign in</h1>
      <LoginForm onDone={() => navigate('/')} />
      <p className="hint">
        Seed login: <code>aaron.forrester@example.com</code>, password
        <code>BankDemo123!</code>.
      </p>
    </div>
  )
}
