const UserProfile = ({ user, onLogout }) => {
    const [activeTab, setActiveTab] = useState('profile');

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950/20 to-slate-950 p-4">
            <div className="absolute inset-0 grid-pattern opacity-20" />

            <div className="relative max-w-7xl mx-auto">
                <div className="glass rounded-2xl shadow-2xl p-8">
                    <div className="flex items-center justify-between mb-8">
                        <div className="flex items-center gap-4">
                            <div className="h-16 w-16 rounded-full bg-gradient-to-br from-blue-500 to-cyan-500 flex items-center justify-center text-white text-2xl font-bold">
                                {user.email[0].toUpperCase()}
                            </div>
                            <div>
                                <h1 className="text-2xl font-bold text-white">{user.email}</h1>
                                <p className="text-gray-400">Subscription: {user.subscription_id?.slice(0, 8)}...</p>
                            </div>
                        </div>
                        <button
                            onClick={onLogout}
                            className="flex items-center gap-2 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors"
                        >
                            <LogOut className="h-4 w-4" />
                            Sign Out
                        </button>
                    </div>

                    <div className="flex gap-6 mb-8 border-b border-white/10">
                        {[
                            { id: 'profile', label: 'Profile', icon: User },
                            { id: 'security', label: 'Security', icon: Shield },
                            { id: 'api', label: 'API Keys', icon: Key },
                            { id: 'usage', label: 'Usage', icon: Activity },
                            { id: 'billing', label: 'Billing', icon: CreditCard },
                        ].map(tab => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors ${activeTab === tab.id
                                        ? 'text-white border-b-2 border-blue-500'
                                        : 'text-gray-400 hover:text-white'
                                    }`}
                            >
                                <tab.icon className="h-4 w-4" />
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    <div className="space-y-6">
                        {activeTab === 'profile' && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">
                                        Full Name
                                    </label>
                                    <input
                                        type="text"
                                        defaultValue="John Doe"
                                        className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">
                                        Organization
                                    </label>
                                    <input
                                        type="text"
                                        defaultValue="Acme Corp"
                                        className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">
                                        Email
                                    </label>
                                    <input
                                        type="email"
                                        value={user.email}
                                        disabled
                                        className="w-full px-4 py-3 bg-slate-800/30 border border-slate-700 rounded-xl text-gray-400"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">
                                        Role
                                    </label>
                                    <select className="w-full px-4 py-3 bg-slate-800/50 border border-slate-700 rounded-xl text-white">
                                        <option>DevOps Engineer</option>
                                        <option>Developer</option>
                                        <option>Administrator</option>
                                    </select>
                                </div>
                            </div>
                        )}

                        {activeTab === 'security' && (
                            <div className="space-y-6">
                                <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700">
                                    <h3 className="text-lg font-medium text-white mb-4">Two-Factor Authentication</h3>
                                    <p className="text-gray-400 mb-4">Add an extra layer of security to your account</p>
                                    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
                                        Enable 2FA
                                    </button>
                                </div>
                                <div className="p-4 bg-slate-800/30 rounded-xl border border-slate-700">
                                    <h3 className="text-lg font-medium text-white mb-4">Change Password</h3>
                                    <button className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors">
                                        Update Password
                                    </button>
                                </div>
                            </div>
                        )}

                        {activeTab === 'api' && (
                            <div className="space-y-4">
                                <div className="flex justify-between items-center">
                                    <h3 className="text-lg font-medium text-white">API Keys</h3>
                                    <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
                                        Generate New Key
                                    </button>
                                </div>
                                <div className="space-y-3">
                                    {['Production API Key', 'Development API Key'].map((key, i) => (
                                        <div key={i} className="p-4 bg-slate-800/30 rounded-xl border border-slate-700 flex items-center justify-between">
                                            <div>
                                                <p className="text-white font-medium">{key}</p>
                                                <p className="text-gray-400 text-sm">Created: {new Date().toLocaleDateString()}</p>
                                            </div>
                                            <button className="text-red-400 hover:text-red-300 transition-colors">
                                                Revoke
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {activeTab === 'usage' && (
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                <div className="p-6 bg-slate-800/30 rounded-xl border border-slate-700">
                                    <h3 className="text-gray-400 text-sm mb-2">API Calls</h3>
                                    <p className="text-3xl font-bold text-white">24,521</p>
                                    <p className="text-green-400 text-sm mt-2">↑ 12% from last month</p>
                                </div>
                                <div className="p-6 bg-slate-800/30 rounded-xl border border-slate-700">
                                    <h3 className="text-gray-400 text-sm mb-2">Deployments</h3>
                                    <p className="text-3xl font-bold text-white">142</p>
                                    <p className="text-green-400 text-sm mt-2">↑ 8% from last month</p>
                                </div>
                                <div className="p-6 bg-slate-800/30 rounded-xl border border-slate-700">
                                    <h3 className="text-gray-400 text-sm mb-2">Resources</h3>
                                    <p className="text-3xl font-bold text-white">89</p>
                                    <p className="text-yellow-400 text-sm mt-2">→ No change</p>
                                </div>
                            </div>
                        )}

                        {activeTab === 'billing' && (
                            <div className="space-y-6">
                                <div className="p-6 bg-gradient-to-r from-blue-500/10 to-cyan-500/10 rounded-xl border border-blue-500/20">
                                    <div className="flex justify-between items-start">
                                        <div>
                                            <h3 className="text-xl font-bold text-white mb-2">Pro Plan</h3>
                                            <p className="text-gray-400">$99/month • Renews on Jan 1, 2025</p>
                                        </div>
                                        <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg transition-colors">
                                            Upgrade Plan
                                        </button>
                                    </div>
                                </div>
                                <div className="space-y-3">
                                    <h3 className="text-lg font-medium text-white">Recent Invoices</h3>
                                    {['December 2024', 'November 2024', 'October 2024'].map((month, i) => (
                                        <div key={i} className="p-4 bg-slate-800/30 rounded-xl border border-slate-700 flex items-center justify-between">
                                            <div>
                                                <p className="text-white">{month}</p>
                                                <p className="text-gray-400 text-sm">$99.00</p>
                                            </div>
                                            <button className="text-blue-400 hover:text-blue-300 transition-colors">
                                                Download
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="mt-8 flex justify-end">
                        <button className="px-6 py-3 bg-gradient-to-r from-blue-500 to-cyan-500 text-white font-semibold rounded-xl hover:from-blue-600 hover:to-cyan-600 transition-all">
                            Save Changes
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};
