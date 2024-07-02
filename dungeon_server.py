import socket
import time
import struct

##########################################
    
MESSAGE_JOIN = 0
MESSAGE_WELCOME = 1
MESSAGE_ACK = 2
MESSAGE_POSITION = 3
MESSAGE_MELEE = 4

##########################################

class Player:
    def __init__(self, player_id, address_and_port):
        self.player_id = player_id
        self.address_and_port = address_and_port
        self.x = 0
        self.y = 0
        self.movement_order = 0
        self.melee_order = 0
        self.reliable_messages = {}     #{MessageID : (Timestamp , Content)}
        self.karma = 3 

##########################################
    
class Server:

    def __init__(self, address, port):
        self.address = address
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.address, self.port))
        self.format = "<IIIff"                                              # format: I - message_type | I - message_id (message_counter) | I - player_id | ff - position
        self.message_counter = 0
        self.clients_counter = 100
        self.clients = {}                                                   # {address : player (struct)}
        self.blacklist = {}                                                 # {(ip, port) : timestamp}

    ##########################################
    
    def decrease_karma(self, player, amount):
        self.clients[player].karma -= amount

        if self.clients[player].karma <= 0:

            del(self.clients[player])
            self.blacklist[player] = time.time()
    
    ##########################################
    
    def send_raw_message(self, destination, payload):

        # Send packet to client address
        self.socket.sendto(payload, destination)
    
    ##########################################
            
    def send_message(self, destination, message_type, payload):

        # Set header (tuple: message type and message counter id)
        header = struct.pack("<II", message_type, self.message_counter)

        # Send packet
        self.send_raw_message(destination, header + payload)

        # Increase global counter (message)
        self.message_counter += 1

        # Return for store into client's reliable messages
        return header + payload, self.message_counter - 1
    
    ##########################################
    
    def send_reliable_message(self, destination, message_type, payload):

        # Send message (type, payload) ang get returned message content (header + payload) and message id
        message, message_id = self.send_message(destination, message_type, payload)

        # Add message (tuple: header + payload) to reliable messages list of client
        self.clients[destination].reliable_messages[message_id] = (time.time(), message)

    ##########################################
            
    def check_reliable_messages(self):
        
        # Get current time
        current_time = time.time()

        # Loop: clients
        for client in self.clients:

            # Loop: pending messages
            for message_id in self.clients[client].reliable_messages:

                # Get current message wrapper
                reliable_message = self.clients[client].reliable_messages[message_id]

                # Get timestamp and content of message
                time_stamp, payload = reliable_message

                # Calculate delta
                delta_time = current_time - time_stamp

                # Check if time limit reached
                if delta_time >= 3.0:
                    
                    # Resend packet
                    self.send_raw_message( client, payload)

                    # Update message with current time
                    self.clients[client].reliable_messages[message_id] = (current_time, payload)

    ##########################################
    
    # Server loop
    def tick(self):

        #print("############################## Start server loop")

        # Check if reliable messages needs resend to clients
        self.check_reliable_messages()
        
        # Get data from clients
        data, sender = self.socket.recvfrom(4096)

        # Check if packet is correct
        if len(data) < 8:
            print("Ignoring broken packet from", sender)
            return
        
        # Unpack data and get infos (only first 8 byte)
        message_type, message_id = struct.unpack("<II", data[:8])
        
        # Log
        # print("MESSAGE TYPE: ",message_type, "FROM: " ,sender, "MESSAGE ID: ", message_id)
        
        # Check if the client is connecting for the first time
        if message_type == MESSAGE_JOIN:

            # Checks if the client is already present in the connected clients
            if sender in self.clients:

                # Punish him
                self.decrease_karma(sender, 1)

            # Accept client's join request
            else:

                self.clients_counter += 1                    # Increase global counter (clients)
                player_id = self.clients_counter + 1         # Set an incremental and unique id to new client
                
                # Init new player
                new_player = Player(player_id, sender)

                # Add client to list (dictionary: address | player struct)
                self.clients[sender] = new_player
                
                # Log
                print("A new player is joined", sender, player_id)

                # Set return packet with payload info (comunicate player_id to new client) 
                payload = struct.pack("<I", player_id)

                # Send packet
                self.send_reliable_message(sender, MESSAGE_WELCOME, payload)

                return

        # Check client's acknowledge
        elif message_type == MESSAGE_ACK:

            # Check if packet is correct
            if len(data) < 0: # != 12
                
                # Log
                print("Ack not right size", sender)
                
                # Punish him
                self.decrease_karma(sender, 2)
                return
            
            # Get message type and unique id 
            reliable_message_type, reliable_message_id = struct.unpack("<II", data[:8])

            # Check if exist in client's reliable messages
            if reliable_message_id not in self.clients[sender].reliable_messages:

                # Log
                print("Failed ACK check, karma decrease!", sender)
                
                # Punish him
                self.decrease_karma(sender, 1)
                return
            
            # Confirmed, delete message from list
            del(self.clients[sender].reliable_messages[reliable_message_id])
                       
            # Log
            print("Ack confirmed! Type: [",reliable_message_type,"]", " from ",sender)

        # Check if client send position
        elif message_type == MESSAGE_POSITION:
            
            # Check if packet is correct 
            if len(data) != 20:

                # Punish him
                self.decrease_karma(sender, 1)
                return
            
            # Get info from data
            player_id, x, y = struct.unpack("<Iff", data[8:20])

            # Check if player id match
            if self.clients[sender].player_id != player_id:

                # Cheating! player id != sender -> move another player
                print("Invalid player_id for", sender)

                # Finish him      
                self.decrease_karma(sender, 5)
                return

            # Check if match
            if message_id <= self.clients[sender].movement_order:
                return
            
            # Set new pos
            self.clients[sender].x = x
            self.clients[sender].y = y

            # Set new message id
            self.clients[sender].movement_order = message_id
            
            # Log
            #print("Player:", player_id, "from:",sender, "move to:", x, y)

            # Set packet
            position_packet = struct.pack("<Iff", player_id, x, y)

            # Loop: clients
            for player in self.clients:

                # Check if match
                if player == sender:
                    continue # Skip owner
                
                # Send packet
                self.send_message(player, MESSAGE_POSITION, position_packet)
        
        # Check if client send melee
        elif message_type == MESSAGE_MELEE:
            
            # Check if packet is correct 
            if len(data) != 20:

                # Punish him
                self.decrease_karma(sender, 1)
                return
            
            # Get info from data
            player_id, = struct.unpack("<I", data[8:12])

            # Check if player id match
            if self.clients[sender].player_id != player_id:

                # Cheating! player id != sender -> move another player
                print("Invalid player_id for", sender)

                # Finish him      
                self.decrease_karma(sender, 5)
                return

            # Check if match
            if message_id <= self.clients[sender].melee_order:
                # Cheating!
                print("Invalid message_id for", sender)
                return
            
            # Set melee
            can_attack = 1

            # Set new message id
            self.clients[sender].melee_order = message_id
            
            # Log
            print("Player:", player_id, "from:",sender, "has used melee attack!")

            # Set packet
            payload = struct.pack("<If", player_id, can_attack)
               
            # Loop: clients
            for player in self.clients:
                
                # Send packet
                self.send_reliable_message(player, MESSAGE_MELEE, payload)
                
        #print("############################## End server loop")
    
    ##########################################
                    
    def run(self):
        while True:
            self.tick()
    
    ##########################################
    
# ENTRY POINT ################################
if __name__ == "__main__":

    # Set address and port of server
    server = Server("192.168.0.2", 9999)

    # Start server
    server.run()
##############################################
