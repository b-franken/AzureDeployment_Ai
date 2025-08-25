export default function AuthenticationFlow() {
    const [currentPage, setCurrentPage] = useState('login');
    const [user, setUser] = useState(null);

    const handleLogin = (userData) => {
        setUser(userData);
        setCurrentPage('profile');
    };

    const handleRegister = (formData) => {
        console.log('Registration data:', formData);
        setCurrentPage('login');
    };

    const handleLogout = () => {
        setUser(null);
        setCurrentPage('login');
    };

    if (user) {
        return <UserProfile user={user} onLogout={handleLogout} />;
    }

    return (
        <>
            {currentPage === 'login' && (
                <LoginPage onLogin={handleLogin} />
            )}
            {currentPage === 'register' && (
                <RegisterPage onRegister={handleRegister} />
            )}
            <div className="fixed bottom-4 right-4 flex gap-2">
                <button
                    onClick={() => setCurrentPage('login')}
                    className={`px-4 py-2 rounded-lg transition-colors ${currentPage === 'login'
                            ? 'bg-blue-500 text-white'
                            : 'bg-slate-800 text-gray-400 hover:text-white'
                        }`}
                >
                    Login
                </button>
                <button
                    onClick={() => setCurrentPage('register')}
                    className={`px-4 py-2 rounded-lg transition-colors ${currentPage === 'register'
                            ? 'bg-blue-500 text-white'
                            : 'bg-slate-800 text-gray-400 hover:text-white'
                        }`}
                >
                    Register
                </button>
            </div>
        </>
    );
}