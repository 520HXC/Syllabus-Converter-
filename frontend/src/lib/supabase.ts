import { createClient } from "@supabase/supabase-js"

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabasePublicKey = import.meta.env.VITE_SUPABASE_PUBLIC_KEY as string | undefined

export const supabase =
  supabaseUrl && supabasePublicKey
    ? createClient(supabaseUrl, supabasePublicKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null

export type AuthMode = "demo" | "supabase"

export function resolveAuthMode(configuredMode: AuthMode | undefined): AuthMode {
  return configuredMode ?? "supabase"
}

export const authMode = resolveAuthMode(
  import.meta.env.VITE_AUTH_MODE as AuthMode | undefined,
)
