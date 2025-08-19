import { PublicClientApplication, AuthenticationResult, BrowserCacheLocation, InteractionRequiredAuthError } from "@azure/msal-browser"

const clientId = process.env.NEXT_PUBLIC_AAD_CLIENT_ID as string
const tenantId = process.env.NEXT_PUBLIC_AAD_TENANT_ID as string
const redirectUri = process.env.NEXT_PUBLIC_AAD_REDIRECT_URI || (typeof window !== "undefined" ? window.location.origin : undefined)
const apiScope = process.env.NEXT_PUBLIC_AAD_API_SCOPE as string 

if (!clientId || !tenantId || !redirectUri || !apiScope) {
  // eslint-disable-next-line no-console
  console.warn("MSAL config is incomplete")
}

export const msal = new PublicClientApplication({
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: BrowserCacheLocation.SessionStorage,
    storeAuthStateInCookie: false,
  },
})

export async function ensureLogin(): Promise<AuthenticationResult> {
  const accounts = msal.getAllAccounts()
  if (accounts.length === 0) {
    await msal.loginRedirect({ scopes: [apiScope] })
    throw new Error("redirecting for login")
  }
  return { ...({} as AuthenticationResult), account: accounts[0] }
}

export async function acquireApiToken(): Promise<string> {
  const accounts = msal.getAllAccounts()
  const account = accounts[0]
  if (!account) {
    await msal.loginRedirect({ scopes: [apiScope] })
    throw new Error("redirecting for login")
  }

  try {
    const res = await msal.acquireTokenSilent({ account, scopes: [apiScope] })
    return res.accessToken
  } catch (e) {
    if (e instanceof InteractionRequiredAuthError) {
      await msal.acquireTokenRedirect({ account, scopes: [apiScope] })
      throw new Error("redirecting for token")
    }
    throw e
  }
}

export async function logout(): Promise<void> {
  const account = msal.getAllAccounts()[0]
  await msal.logoutRedirect({ account })
}
