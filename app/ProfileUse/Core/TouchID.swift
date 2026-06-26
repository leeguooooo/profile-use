import Foundation
import LocalAuthentication

/// Native Touch ID / password gate. The GUI confirms the user here, then runs
/// the CLI unattended (`--no-confirm`). Falls back to the device password.
enum BiometricGate {
    static func confirm(reason: String) async -> Bool {
        let context = LAContext()
        context.localizedFallbackTitle = "Use Password"

        var error: NSError?
        let policy: LAPolicy = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
            ? .deviceOwnerAuthenticationWithBiometrics
            : .deviceOwnerAuthentication

        // If no auth is configured at all, don't hard-block the user's own machine.
        guard context.canEvaluatePolicy(policy, error: &error) else { return true }

        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(policy, localizedReason: reason) { success, _ in
                continuation.resume(returning: success)
            }
        }
    }
}
