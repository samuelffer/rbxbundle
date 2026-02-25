-- Extracted from RBXMX
-- Class: ModuleScript
-- Name: World_CONFIG
-- Path: ReplicatedStorage/Flight/World_CONFIG

return {
	Atmosphere = {
		RhoSeaLevel = 0.015,
		AltitudeFalloff = 0.00006, -- se for linear
		-- ou use ScaleHeight se for exponencial:
		-- ScaleHeight = 8000,
	},
	Debug = {
		ForceScale = 200,
	},
	Wind = {
		Enabled = true,
	}
}