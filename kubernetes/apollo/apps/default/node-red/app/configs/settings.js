const credentialSecret = process.env.NODE_RED_CREDENTIAL_SECRET;

if (!credentialSecret) {
    throw new Error("NODE_RED_CREDENTIAL_SECRET is required");
}

module.exports = {
    flowFile: "flows.json",
    flowFilePretty: true,
    credentialSecret,
    uiPort: 1880,
    functionExternalModules: true,
    editorTheme: {
        projects: {
            enabled: true,
            workflow: { mode: "manual" }
        }
    }
};
