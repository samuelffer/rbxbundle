-- Extracted from RBXMX
-- Class: Script
-- Name: NetworkOwner
-- Path: ServerScriptService/NetworkOwner

local function Seated(active, seat)
	if active == false then return end
	if seat.Name ~= "Plane_Seat" then return end
	local player = game.Players:GetPlayerFromCharacter(seat.Occupant.Parent)
	if player == nil then return end
	seat:SetNetworkOwner(player)
	print("SetNetworkOwner: ", player.DisplayName)
end

local function CharacterAdded(character)
	character.Humanoid.Seated:Connect(Seated)
end

local function PlayerAdded(player)
	player.CharacterAdded:Connect(CharacterAdded)
end

game.Players.PlayerAdded:Connect(PlayerAdded)