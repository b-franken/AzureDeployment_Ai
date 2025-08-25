// Registration Page Component
const RegisterPage = ({ onRegister }) => {
    const [formData, setFormData] = useState({
        fullName: '',
        email: '',
        password: '',
        confirmPassword: '',
        organization: '',
        role: 'developer'
    });
    const [showPassword, setShowPassword] = useState(false);
    const [acceptTerms, setAcceptTerms] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [errors, setErrors] = useState({});

    const passwordStrength = (password) => {
        if (!password) return 0;
        let strength = 0;
        if (password.length >= 8) strength++;
        if (password.match(/[a-z]/) && password.match(/[A-Z]/)) strength++;
        if (password.match(/[0-9]/)) strength++;
        if (password.match(/[^a-zA-Z0-9]/)) strength++;
        return strength;
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const newErrors = {};

        if (formData.password !== formData.confirmPassword) {
            newErrors.confirmPassword = "Passwords don't match";
        }
        if (passwordStrength(formData.password) < 2) {
            newErrors.password = "Password is too weak";
        }
        if (!acceptTerms) {
            newErrors.terms = "You must accept the terms and conditions";
        }

        if (Object.keys(newErrors).length > 0) {
            setErrors(newErrors);
            return;
        }

        setIsLoading(true);
        try {
            await new Promise(resolve => setTimeout(resolve, 1500));
            onRegister(formData);
        } finally {
            setIsLoading(false);
        }
    };

    const strength = passwordStrength(formData.password);
    const strengthColors = ['bg-gray-600', 'bg-red-500', 'bg-yellow-500', 'bg-green-500', 'bg-green-600'];
    const strengthLabels = ['', 'Weak', 'Fair', 'Good', 'Strong'];

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950/20 to-slate-950 flex items-center justify-center p-4">
            <div className="absolute inset-0 grid-pattern opacity-20" />

            <div className="relative w-full max-w-2xl">
                <div className="absolute -top-20 -left-20 w-72 h-72 bg-blue-500/20 rounded-full blur-3xl animate-pulse" />
                <div className="absolute -bottom-20 -right-20 w-96 h-96 bg-cyan-500/20 rounded-full blur-3xl animate-pulse animation-delay-2000" />

                <div className="relative bg-slate-900/80 backdrop-blur-xl rounded-2xl shadow-2xl border border-white/10 p-8">
                    <div className="text-center mb-8">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 shadow-lg shadow-blue-500/25 mb-4">
                            <User className="h-8 w-8 text-white" />
                        </div>
                        <h1 className="text-2xl font-bold text-white">Create Account</h1>
                        <p className="text-gray-400 mt-2">Join DevOps AI Platform today</p>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-6">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Full Name
                                </label>
                                <input
                                    type="text"
                                    value={formData.fullName}
                                    onChange={(e) => setFormData({ ...formData, fullName: e.target.value })}
                                    className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                                    placeholder="John Doe"
                                    required
                                />
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Organization
                                </label>
                                <input
                                    type="text"
                                    value={formData.organization}
                                    onChange={(e) => setFormData({ ...formData, organization: e.target.value })}
                                    className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                                    placeholder="Acme Corp"
                                    required
                                />
                            </div>
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">
                                Email Address
                            </label>
                            <input
                                type="email"
                                value={formData.email}
                                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                                className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                                placeholder="john@example.com"
                                required
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">
                                Role
                            </label>
                            <select
                                value={formData.role}
                                onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                                className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                            >
                                <option value="developer">Developer</option>
                                <option value="devops">DevOps Engineer</option>
                                <option value="architect">Solution Architect</option>
                                <option value="manager">Engineering Manager</option>
                                <option value="admin">Administrator</option>
                            </select>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Password
                                </label>
                                <div className="relative">
                                    <input
                                        type={showPassword ? "text" : "password"}
                                        value={formData.password}
                                        onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                        className={`w-full pr-12 px-4 py-3 bg-slate-800/50 border ${errors.password ? 'border-red-500' : 'border-slate-700'} rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all`}
                                        placeholder="Strong password"
                                        required
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                                    >
                                        {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                                    </button>
                                </div>
                                {formData.password && (
                                    <div className="mt-2">
                                        <div className="flex gap-1">
                                            {[...Array(4)].map((_, i) => (
                                                <div
                                                    key={i}
                                                    className={`h-1 flex-1 rounded-full ${i < strength ? strengthColors[strength] : 'bg-gray-700'}`}
                                                />
                                            ))}
                                        </div>
                                        <p className="text-xs mt-1 text-gray-400">
                                            Strength: <span className={strength > 2 ? 'text-green-400' : 'text-yellow-400'}>{strengthLabels[strength]}</span>
                                        </p>
                                    </div>
                                )}
                                {errors.password && (
                                    <p className="text-xs text-red-400 mt-1">{errors.password}</p>
                                )}
                            </div>

                            <div>
                                <label className="block text-sm font-medium text-gray-300 mb-2">
                                    Confirm Password
                                </label>
                                <input
                                    type={showPassword ? "text" : "password"}
                                    value={formData.confirmPassword}
                                    onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                                    className={`w-full px-4 py-3 bg-slate-800/50 border ${errors.confirmPassword ? 'border-red-500' : 'border-slate-700'} rounded-xl text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all`}
                                    placeholder="Confirm password"
                                    required
                                />
                                {errors.confirmPassword && (
                                    <p className="text-xs text-red-400 mt-1">{errors.confirmPassword}</p>
                                )}
                            </div>
                        </div>

                        <div>
                            <label className="flex items-start">
                                <input
                                    type="checkbox"
                                    checked={acceptTerms}
                                    onChange={(e) => setAcceptTerms(e.target.checked)}
                                    className="w-4 h-4 mt-1 bg-slate-800 border-slate-700 rounded text-blue-500 focus:ring-blue-500"
                                />
                                <span className="ml-2 text-sm text-gray-400">
                                    I agree to the{' '}
                                    <a href="#" className="text-blue-400 hover:text-blue-300">Terms of Service</a>
                                    {' '}and{' '}
                                    <a href="#" className="text-blue-400 hover:text-blue-300">Privacy Policy</a>
                                </span>
                            </label>
                            {errors.terms && (
                                <p className="text-xs text-red-400 mt-1">{errors.terms}</p>
                            )}
                        </div>

                        <button
                            type="submit"
                            disabled={isLoading || !acceptTerms}
                            className="w-full py-3 px-4 bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold rounded-xl shadow-lg hover:from-blue-600 hover:to-cyan-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-60 disabled:cursor-not-allowed transition-all duration-200 transform hover:scale-[1.02]"
                        >
                            {isLoading ? 'Creating Account...' : 'Create Account'}
                        </button>
                    </form>

                    <div className="mt-8 text-center">
                        <p className="text-gray-400 text-sm">
                            Already have an account?{' '}
                            <a href="#login" className="text-blue-400 hover:text-blue-300 font-medium transition-colors">
                                Sign in
                            </a>
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};