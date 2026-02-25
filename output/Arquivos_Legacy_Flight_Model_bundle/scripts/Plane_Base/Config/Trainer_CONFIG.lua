-- Extracted from RBXMX
-- Class: ModuleScript
-- Name: Trainer_CONFIG
-- Path: Plane_Base/Config/Trainer_CONFIG

return {
	Engine = {
		EnginePartName = "Engine",
		MaxThrust = 90000,
		UseThrottleFloat = false, -- começa FALSE pra não quebrar sua lógica atual
		ThrottleRate = 10000,       -- usado pelo seu Shift/Ctrl
		AllowReverse = false,
	},

	Naming = {
		BaseModelName = "Plane_Base",
		SeatName = "Plane_Seat",
	}
}