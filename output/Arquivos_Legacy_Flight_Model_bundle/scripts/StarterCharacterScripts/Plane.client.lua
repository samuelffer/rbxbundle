-- Extracted from RBXMX
-- Class: LocalScript
-- Name: Plane
-- Path: StarterCharacterScripts/Plane

local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local character = script.Parent
local humanoid = character:WaitForChild("Humanoid")
local connection = nil
local seat = nil
local CFG = nil
local planeModel = nil
local bodyPart = nil
local parts = {}
local hinges = {}
local thrust = 0


local ReplicatedStorage = game:GetService("ReplicatedStorage")
local remote = ReplicatedStorage:WaitForChild("PlaneControls")
local WorldCFG = require(ReplicatedStorage:WaitForChild("Flight"):WaitForChild("World_CONFIG"))

local rudder = 0
local RUDDER_SPEED = 3
local RUDDER_RETURN = 5

local flapNotches = {0, 0.25, 0.5, 0.75, 1}
local flapIndex = 1
local flaps = flapNotches[flapIndex]

-- tuning (você ajusta)
local FLAP_LIFT_GAIN = 4  -- +80% de lift no flap quando flaps=1
local FLAP_DRAG_GAIN = 1.2  -- +120% de drag no flap quando flaps=1

local sendTimer = 0
local lastSent = 999


local function Start()
	local model = seat:FindFirstAncestor("Plane_Base")
	planeModel = model
	bodyPart = model:FindFirstChild("Body") or model.PrimaryPart
	for index, descendant in model:GetDescendants() do
		if descendant:IsA("BasePart") == true then
			local attachment0 = Instance.new("Attachment", descendant)
			local attachment1 = Instance.new("Attachment", descendant)

			local beam = Instance.new("Beam")
			beam.FaceCamera = true
			beam.Segments = 1
			beam.Width0 = 0.2
			beam.Width1 = 0.2
			beam.Color = ColorSequence.new(Color3.new(1, 0, 0))
			beam.Attachment0 = attachment0
			beam.Attachment1 = attachment1
			beam.Parent = descendant

			local vectorForce = Instance.new("VectorForce")
			vectorForce.Attachment0 = attachment0
			vectorForce.Parent = descendant

			--Armazena as attachments e as beams para destruir depois
			table.insert(parts, {
				Part = descendant,
				Attachment0 = attachment0,
				Attachment1 = attachment1,
				Beam = beam,
				VectorForce = vectorForce,
				AreaX = descendant.Size.Y * descendant.Size.Z,
				AreaY = descendant.Size.X * descendant.Size.Z,
				AreaZ = descendant.Size.X * descendant.Size.Y,
				IsFlap = (descendant:GetAttribute("IsFlap") == true),
			})

		elseif descendant.ClassName == "HingeConstraint" then
			table.insert(hinges, descendant)

		end
	end
end

--Ao parar de sentar, destrói as attachments e as beams
local function Stop()
	for index, data in parts do
		data.Attachment0:Destroy()
		data.Attachment1:Destroy()
		data.Beam:Destroy()
		data.VectorForce:Destroy()
	end
	table.clear(parts)
	table.clear(hinges)
	
	if gearWheels then
		for _, w in gearWheels do
			if w.vf then w.vf:Destroy() end
			if w.a0 then w.a0:Destroy() end
		end
	end
end



local function Loop(deltaTime)
	if not CFG then return end
	local rate = CFG.Engine.ThrottleRate
	if UserInputService:IsKeyDown(Enum.KeyCode.LeftShift) then thrust += rate * deltaTime end
	if UserInputService:IsKeyDown(Enum.KeyCode.LeftControl) then thrust -= rate * deltaTime end

	-- INPUT RUDDER (Q/E) - sem suavizar, hinge que suaviza
	local left  = UserInputService:IsKeyDown(Enum.KeyCode.Q)
	local right = UserInputService:IsKeyDown(Enum.KeyCode.E)
	
	-- INPUT FLAPS (F/G)
	if UserInputService:IsKeyDown(Enum.KeyCode.F) then
		flapIndex = math.clamp(flapIndex + 1, 1, #flapNotches)
		flaps = flapNotches[flapIndex]
	end

	if UserInputService:IsKeyDown(Enum.KeyCode.G) then
		flapIndex = math.clamp(flapIndex - 1, 1, #flapNotches)
		flaps = flapNotches[flapIndex]
	end

	local rudderRaw = 0
	if left and not right then
		rudderRaw = -1
	elseif right and not left then
		rudderRaw = 1
	end

	rudder = rudderRaw

	-- envia pro servidor
	sendTimer += deltaTime
	if seat and sendTimer >= 0.05 then
		sendTimer = 0
		if math.abs(rudder - lastSent) > 0.01 or true then
			lastSent = rudder
			remote:FireServer(seat, {
				Rudder = rudder,
				Flaps = flaps
			})
		end
	end
	
	

	--Calcula a força de arrasto e a força de impulso
	for index, data in parts do
		local h = math.max(0, data.Part.Position.Y)
		local normalizedAirDensity = math.clamp(1 - h * WorldCFG.Atmosphere.AltitudeFalloff, 0, 1)
		local airDensity = normalizedAirDensity * WorldCFG.Atmosphere.RhoSeaLevel

		local wind = (WorldCFG.Wind.Enabled and workspace.GlobalWind) or Vector3.zero
		local velocity = -data.Part:GetVelocityAtPosition(data.Part.Position) + wind


		if data.Part.Name == "Engine" then
			thrust = math.clamp(thrust, 0, CFG.Engine.MaxThrust)
			data.VectorForce.Force = Vector3.new(0, 0, -thrust * normalizedAirDensity)
		else
			data.VectorForce.Force = Vector3.zero
		end

		if velocity.Magnitude > 0 then
			local vhat = velocity.Unit
			local v2 = velocity.Magnitude * velocity.Magnitude

			-- referência "fixa" pra não deixar o flap inverter lift ao girar
			local refUp = (bodyPart and bodyPart.CFrame.UpVector) or data.Part.CFrame.UpVector

			local dotRight = data.Part.CFrame.RightVector:Dot(vhat)
			local dotUp = (data.IsFlap and refUp or data.Part.CFrame.UpVector):Dot(vhat)

			if data.IsFlap then
				dotUp = -dotUp
			end
			
			local dotLook = data.Part.CFrame.LookVector:Dot(vhat)

			-- ganhos só pro flap
			local liftMul = 1
			local dragMul = 1
			if data.IsFlap then
				liftMul = 1 + FLAP_LIFT_GAIN * flaps
				dragMul = 1 + FLAP_DRAG_GAIN * flaps
			end

			data.VectorForce.Force += Vector3.xAxis * airDensity * dotRight * data.AreaX * v2
			data.VectorForce.Force += Vector3.yAxis * airDensity * dotUp    * data.AreaY * v2 * liftMul
			data.VectorForce.Force -= Vector3.zAxis * airDensity * dotLook  * data.AreaZ * v2 * dragMul
		end

		data.Attachment1.Position = data.VectorForce.Force / WorldCFG.Debug.ForceScale
	end


	for _, hinge in hinges do
		hinge.TargetAngle = 0

		for name, mult in hinge:GetAttributes() do
			local v = nil

			-- tenta ler property do VehicleSeat (ThrottleFloat/SteerFloat etc)
			local ok, propValue = pcall(function()
				return seat[name]
			end)

			if ok then
				v = propValue
			else
				-- se não existir como property, tenta como Attribute (Rudder)
				v = seat:GetAttribute(name)
			end

			if type(v) ~= "number" then
				v = 0
			end

			hinge.TargetAngle += v * mult
		end
	end
end


--Quando o jogador senta, cria as attachments e as beams
local function Seated(active, currentSeat)
	if active == false then
		if connection == nil then return end
		connection:Disconnect()
		connection = nil
		Stop()
		CFG = nil
		seat = nil
	elseif currentSeat.Name == "Plane_Seat" then
		seat = currentSeat

		local model = seat:FindFirstAncestor("Plane_Base")
		local cfgFolder = model:WaitForChild("Config")
		local configName = model:GetAttribute("CurrentConfig") or "Trainer_CONFIG"
		CFG = require(cfgFolder:WaitForChild(configName))
		

		Start()
		connection = RunService.PostSimulation:Connect(Loop)
	end
end

humanoid.Seated:Connect(Seated)
