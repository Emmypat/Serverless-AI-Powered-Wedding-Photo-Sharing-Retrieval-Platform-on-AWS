resource "aws_rekognition_collection" "wedding_faces" {
  collection_id = local.rekognition_collection_id
}
